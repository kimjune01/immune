#!/usr/bin/env python3
"""immune — second-order receipt validator for OSS PR review.

Runs Filter + Attend cells of the maintainer-side pipeline (per The Natural
Framework). Outputs a JSON verdict the maintainer can scan in seconds.

Usage:
    immune scan <pr-url>
    immune scan owner/repo#123

Env (filter):
    GITHUB_TOKEN                       required

Env (attend — agent runtime is a headless CLI, not a Python SDK):
    IMMUNE_AGENT                       'claude' (default), 'codex', or 'gemini'
    IMMUNE_HG_FANOUT                   number of parallel hypothesis perturbations
                                       (default 3, set 0 to disable HG generation)

    claude (Anthropic family):
        ANTHROPIC_API_KEY              direct API
        CLAUDE_CODE_USE_VERTEX=1 + GOOGLE_APPLICATION_CREDENTIALS + ...
        CLAUDE_CODE_USE_BEDROCK=1 + AWS_*
    codex (OpenAI family):
        OPENAI_API_KEY
    gemini (Google):
        GEMINI_API_KEY  (or GOOGLE_API_KEY)

If you want a different runtime, swap the CLI in your workflow file — immune
just shells out to whatever IMMUNE_AGENT names. Three are supported out of
the box because they're the popular drop-ins; anything else is a one-line
edit to your action wrapper.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# CLI parsing


@dataclass
class PR:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"


def parse_pr(s: str) -> PR:
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", s)
    if m:
        return PR(m[1], m[2], int(m[3]))
    m = re.match(r"([^/]+)/([^#]+)#(\d+)", s)
    if m:
        return PR(m[1], m[2], int(m[3]))
    raise SystemExit(f"unrecognized PR ref: {s!r}")


# ---------------------------------------------------------------------------
# gh wrapper


def gh(path: str, *, fields: str | None = None) -> Any:
    cmd = ["gh", "api", path]
    if fields:
        cmd += ["--jq", fields]
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return None
    if not out.strip():
        return None
    if fields:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return out.strip()
    return json.loads(out)


# ---------------------------------------------------------------------------
# Filter cell — cheap mechanical checks


@dataclass
class FilterReport:
    duplicate_score: float = 0.0
    duplicate_of: str | None = None
    contributor_reputation: dict[str, int] = field(default_factory=dict)
    diff_size_ratio: float = 0.0
    ai_policy_violation: str | None = None
    body_count_verdict: str = "ok"
    verdict: str = "pass"  # pass | warn | reject
    reasons: list[str] = field(default_factory=list)


def filter_duplicate(pr: PR, this_pr: dict) -> tuple[float, str | None]:
    """Hash similarity vs recent merged/closed PRs in this repo.

    Cheap proxy: compare the touched-files set as a sorted joined string.
    Real implementation should use diff-content shingling.
    """
    files = gh(f"repos/{pr.slug}/pulls/{pr.number}/files", fields=".[].filename")
    if not isinstance(files, list):
        files = (files or "").splitlines()
    sig = hashlib.sha256(("\n".join(sorted(files))).encode()).hexdigest()[:16]

    recent = gh(
        f"repos/{pr.slug}/pulls?state=closed&per_page=30&sort=updated&direction=desc",
        fields=".[].number",
    )
    if not isinstance(recent, list):
        recent = (recent or "").splitlines()

    for n in recent[:30]:
        if str(n).strip() == "" or int(n) == pr.number:
            continue
        rfiles = gh(f"repos/{pr.slug}/pulls/{n}/files", fields=".[].filename")
        if not isinstance(rfiles, list):
            rfiles = (rfiles or "").splitlines()
        rsig = hashlib.sha256(("\n".join(sorted(rfiles))).encode()).hexdigest()[:16]
        if rsig == sig:
            return 1.0, f"#{n}"
    return 0.0, None


def filter_reputation(pr: PR, author: str) -> dict[str, int]:
    """Per-repo merge / close / silent count for this author.

    Silent = open PR with no human review activity > 14 days.
    """
    merged = gh(
        f"search/issues?q=repo:{pr.slug}+author:{author}+is:pr+is:merged",
        fields=".total_count",
    )
    closed = gh(
        f"search/issues?q=repo:{pr.slug}+author:{author}+is:pr+is:closed+is:unmerged",
        fields=".total_count",
    )
    open_ = gh(
        f"search/issues?q=repo:{pr.slug}+author:{author}+is:pr+is:open",
        fields=".total_count",
    )
    return {
        "merged": int(merged or 0),
        "closed": int(closed or 0),
        "open": int(open_ or 0),
    }


def filter_diff_size(pr: PR, this_pr: dict) -> float:
    """Ratio of this PR's size to repo's median external-merge size."""
    additions = this_pr.get("additions", 0) + this_pr.get("deletions", 0)
    recent_merged = gh(
        f"search/issues?q=repo:{pr.slug}+is:pr+is:merged&per_page=30",
        fields=".items[].number",
    )
    if not isinstance(recent_merged, list):
        recent_merged = (recent_merged or "").splitlines()

    sizes: list[int] = []
    for n in recent_merged[:20]:
        if str(n).strip() == "":
            continue
        d = gh(f"repos/{pr.slug}/pulls/{n}", fields=".additions+.deletions")
        if d is not None:
            try:
                sizes.append(int(d))
            except (TypeError, ValueError):
                pass
    if not sizes:
        return 1.0
    sizes.sort()
    median = sizes[len(sizes) // 2] or 1
    return additions / median


def filter_ai_policy(pr: PR) -> str | None:
    """Check CONTRIBUTING.md and AGENTS.md for AI prohibition."""
    for path in ("CONTRIBUTING.md", "AGENTS.md", ".github/CONTRIBUTING.md", ".github/AGENTS.md"):
        content = gh(f"repos/{pr.slug}/contents/{path}")
        if not content:
            continue
        try:
            import base64

            body = base64.b64decode(content.get("content", "")).decode("utf-8", errors="ignore")
        except Exception:
            continue
        if re.search(
            r"(reject|prohibit|forbid|do not (submit|open)|no (ai|llm|generative))[^\n]{0,80}(ai|llm|generative|generated|copilot|chatgpt|claude)",
            body,
            re.IGNORECASE,
        ):
            return path
    return None


def run_filter(pr: PR, this_pr: dict) -> FilterReport:
    r = FilterReport()
    author = this_pr.get("user", {}).get("login", "")

    r.duplicate_score, r.duplicate_of = filter_duplicate(pr, this_pr)
    r.contributor_reputation = filter_reputation(pr, author)
    r.diff_size_ratio = filter_diff_size(pr, this_pr)
    r.ai_policy_violation = filter_ai_policy(pr)

    if r.ai_policy_violation:
        r.verdict = "reject"
        r.reasons.append(f"AI prohibited per {r.ai_policy_violation}")
    if r.duplicate_score >= 1.0:
        r.verdict = "reject"
        r.reasons.append(f"duplicate of {r.duplicate_of}")
    if r.diff_size_ratio > 3.0:
        if r.verdict == "pass":
            r.verdict = "warn"
        r.reasons.append(f"diff is {r.diff_size_ratio:.1f}x repo median")
    rep = r.contributor_reputation
    if rep.get("closed", 0) >= 3 and rep.get("merged", 0) == 0:
        r.verdict = "reject"
        r.reasons.append(f"3+ closures, 0 merges in this repo")
    return r


# ---------------------------------------------------------------------------
# Attend cell — receipt validation


@dataclass
class AttendReport:
    hypothesis_graph_present: bool = False
    attestation_path: str | None = None
    attestation_sha256_verified: bool | None = None
    test_replay: dict[str, Any] | None = None
    legibility_verdict: str | None = None
    legibility_reason: str | None = None
    hypothesis_graph_built: dict[str, Any] | None = None
    verdict: str = "pass"  # pass | warn | needs_human
    reasons: list[str] = field(default_factory=list)


HYPOTHESIS_GRAPH_PATTERNS = [
    r"##\s*Hypothesis\s*[Gg]raph",
    r"H0[:\s].*\n.*H1[:\s]",
    r"\bperturbation\b.*\bclassif",
]


def attend_hypothesis_graph(body: str) -> bool:
    if not body:
        return False
    for pat in HYPOTHESIS_GRAPH_PATTERNS:
        if re.search(pat, body, re.MULTILINE | re.DOTALL):
            return True
    return False


def attend_attestation(body: str) -> tuple[str | None, bool | None]:
    """Find an attestation file URL in the PR body and verify its sha256.

    Looks for the pattern: `attestation_path: <url-or-path>` with optional
    `attestation_sha256: <hex>` nearby.
    """
    path_m = re.search(r"attestation[_\s-]?path[:\s]+`?(\S+?)`?\s*$", body, re.MULTILINE | re.IGNORECASE)
    sha_m = re.search(r"attestation[_\s-]?sha256[:\s]+`?([a-f0-9]{64})`?", body, re.IGNORECASE)
    if not path_m:
        return None, None
    path = path_m.group(1)
    if not sha_m:
        return path, None

    expected = sha_m.group(1).lower()
    try:
        if path.startswith(("http://", "https://")):
            with urllib.request.urlopen(path, timeout=10) as resp:
                content = resp.read()
        elif os.path.exists(path):
            with open(path, "rb") as fh:
                content = fh.read()
        else:
            return path, None
    except Exception:
        return path, False

    actual = hashlib.sha256(content).hexdigest()
    return path, actual == expected


# Headless agent runtime. Two CLIs are supported: `claude` (Anthropic family,
# routes Anthropic direct / Vertex / Bedrock via CLAUDE_CODE_USE_* env vars)
# and `codex` (OpenAI family). No Python SDK dependency — every model call is
# a subprocess invocation, so credentials live in env vars and the action's
# attack surface is "what the CLI can read", not "what we imported".


_SUPPORTED_AGENTS = ("claude", "codex", "gemini")


def _agent() -> str:
    """Return 'claude', 'codex', or 'gemini'. Explicit IMMUNE_AGENT wins; else auto-detect."""
    explicit = os.environ.get("IMMUNE_AGENT", "").strip().lower()
    if explicit in _SUPPORTED_AGENTS:
        return explicit
    if os.environ.get("OPENAI_API_KEY"):
        return "codex"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "claude"


def _agent_available(agent: str) -> bool:
    return subprocess.call(["which", agent], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def _agent_cmd(agent: str) -> list[str]:
    if agent == "claude":
        return ["claude", "--print"]
    if agent == "codex":
        return ["codex", "exec", "-"]
    if agent == "gemini":
        return ["gemini", "--yolo", "-p", "-"]
    raise ValueError(f"unsupported agent: {agent}")


def _spawn_agent(prompt: str, *, timeout: int = 90) -> tuple[str | None, str | None]:
    """Run the configured headless CLI with `prompt` on stdin.

    Returns (stdout, error). On success, error is None. On any failure
    (CLI missing, non-zero exit, timeout), stdout is None and error
    explains why — no exception is raised.
    """
    agent = _agent()
    if not _agent_available(agent):
        return None, f"skip ({agent} CLI not on PATH)"
    try:
        out = subprocess.run(
            _agent_cmd(agent), input=prompt, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s ({agent})"
    except OSError as e:
        return None, f"spawn failed ({agent}): {e!s}"
    if out.returncode != 0:
        return None, f"non-zero exit ({agent}): {out.stderr.strip()[:200]}"
    text = (out.stdout or "").strip()
    return (text, None) if text else (None, f"empty output ({agent})")


def attend_legibility(body: str, title: str, diff_summary: str) -> tuple[str | None, str | None]:
    """WHY vs WHAT description check via the configured headless agent."""
    prompt = (
        f"PR title: {title}\nPR body: {body}\nDiff stats: {diff_summary}\n\n"
        "Does this PR description explain WHY the change is correct (root cause, "
        "design rationale), or does it only describe WHAT changed (restating the "
        "diff)? Answer exactly: WHY or WHAT, then one sentence explaining your "
        "judgment."
    )
    text, err = _spawn_agent(prompt, timeout=30)
    if text is None:
        return None, err
    if text.upper().startswith("WHY"):
        return "why", text
    if text.upper().startswith("WHAT"):
        return "what", text
    return None, text


# ---------------------------------------------------------------------------
# In-memory hypothesis graph builder
#
# Spawns K parallel headless-agent perturbations on the PR. Each perturbation
# has a distinct angle (correctness risk, edge cases, scope/conflict). Results
# are aggregated into an HG markdown block included in the synthesis comment.
# Nothing is persisted across PRs — the graph lives only in this process.

_HG_PERTURBATIONS = [
    ("H1-correctness", "What is most likely to be SUBTLY WRONG with this PR's approach? Identify one specific failure mode that would slip through casual review. Reply in 2 lines: line 1 names the failure, line 2 names a perturbation that would expose it."),
    ("H2-edge-cases",  "What input class or edge case does this diff fail to handle? Be concrete (a value, a shape, a state). Reply in 2 lines: line 1 names the unhandled case, line 2 names the trajectory shape (convergent / divergent / oscillatory / chaotic) you'd expect when probing it."),
    ("H3-scope",       "Does this PR's diff scope match its stated intent, or does it touch files / functions outside what the title claims? Reply in 2 lines: line 1 lists out-of-scope changes (or 'none'), line 2 names the risk this introduces."),
]


def attend_hypothesis_graph_build(body: str, title: str, diff_summary: str, k: int = 3) -> dict[str, Any] | None:
    """Generate an in-memory HG by fanning out K perturbation prompts.

    Returns a dict with `nodes` (list of {id, prompt, response, error}) and
    `agent` (which CLI ran them). Returns None when fan-out is disabled
    (k <= 0) or no agent is on PATH.
    """
    if k <= 0:
        return None
    agent = _agent()
    if not _agent_available(agent):
        return {"agent": agent, "nodes": [], "skip": f"{agent} CLI not on PATH"}

    base_context = (
        f"You are running as one perturbation in a hypothesis graph. PR under review:\n\n"
        f"Title: {title}\nBody: {body[:2000]}\nDiff stats: {diff_summary}\n\n"
    )
    nodes: list[dict[str, Any]] = []
    perturbations = _HG_PERTURBATIONS[:max(1, min(k, len(_HG_PERTURBATIONS)))]

    # Run perturbations in parallel via threads (each spawns a subprocess).
    import concurrent.futures
    def _run(p: tuple[str, str]) -> dict[str, Any]:
        node_id, ask = p
        text, err = _spawn_agent(base_context + ask, timeout=60)
        return {"id": node_id, "prompt": ask, "response": text, "error": err}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(perturbations)) as ex:
        nodes = list(ex.map(_run, perturbations))

    return {"agent": agent, "nodes": nodes}


def render_hypothesis_graph(hg: dict[str, Any] | None) -> str:
    """Render the in-memory HG as a markdown block for inclusion in the synthesis comment."""
    if hg is None:
        return ""
    if hg.get("skip"):
        return f"\n\n**Hypothesis graph:** skipped ({hg['skip']})\n"
    lines = [f"\n\n**Hypothesis graph** (built in-memory by {hg.get('agent','?')}, K={len(hg['nodes'])}):\n"]
    for n in hg["nodes"]:
        lines.append(f"\n- **{n['id']}**")
        if n.get("error"):
            lines.append(f"  - error: {n['error']}")
        elif n.get("response"):
            for ln in n["response"].splitlines():
                if ln.strip():
                    lines.append(f"  - {ln.strip()}")
    return "\n".join(lines) + "\n"


def run_attend(pr: PR, this_pr: dict) -> AttendReport:
    r = AttendReport()
    body = this_pr.get("body") or ""
    title = this_pr.get("title", "")

    r.hypothesis_graph_present = attend_hypothesis_graph(body)
    r.attestation_path, r.attestation_sha256_verified = attend_attestation(body)

    diff_summary = (
        f"+{this_pr.get('additions', '?')}/-{this_pr.get('deletions', '?')} "
        f"across {this_pr.get('changed_files', '?')} files"
    )
    r.legibility_verdict, r.legibility_reason = attend_legibility(body, title, diff_summary)

    try:
        k = int(os.environ.get("IMMUNE_HG_FANOUT", "3"))
    except ValueError:
        k = 3
    r.hypothesis_graph_built = attend_hypothesis_graph_build(body, title, diff_summary, k=k)

    # Test replay is the heaviest check; stub for MVP.
    r.test_replay = {"status": "not_implemented_in_mvp"}

    if r.attestation_path and r.attestation_sha256_verified is False:
        r.verdict = "needs_human"
        r.reasons.append("attestation sha256 mismatch — fabricated or tampered")
    elif r.attestation_path and r.attestation_sha256_verified:
        pass  # trusted
    elif r.hypothesis_graph_present:
        if r.verdict == "pass":
            r.verdict = "warn"
        r.reasons.append("hypothesis graph present but no attestation file linked")
    else:
        if r.verdict == "pass":
            r.verdict = "warn"
        r.reasons.append("no receipts (no hypothesis graph, no attestation)")

    if r.legibility_verdict == "what":
        if r.verdict == "pass":
            r.verdict = "warn"
        r.reasons.append("describes WHAT not WHY")

    return r


# ---------------------------------------------------------------------------
# Verdict aggregation


def aggregate(filter_r: FilterReport, attend_r: AttendReport) -> str:
    if filter_r.verdict == "reject":
        return "reject"
    if attend_r.verdict == "needs_human":
        return "needs_human"
    if filter_r.verdict == "warn" or attend_r.verdict == "warn":
        return "suspect"
    return "trusted"


# ---------------------------------------------------------------------------
# Output


def emit_receipt(pr: PR, filter_r: FilterReport, attend_r: AttendReport, verdict: str) -> dict:
    return {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "action": "immune_scan",
        "pr": f"{pr.slug}#{pr.number}",
        "verdict": verdict,
        "filter": asdict(filter_r),
        "attend": asdict(attend_r),
        "schema_version": "0.1",
    }


def emit_markdown(receipt: dict) -> str:
    f = receipt["filter"]
    a = receipt["attend"]
    rep = f.get("contributor_reputation", {})
    rows = [
        f"| Verdict | **{receipt['verdict']}** |",
        f"| Filter | {f['verdict']} ({', '.join(f['reasons']) or 'no flags'}) |",
        f"| Attend | {a['verdict']} ({', '.join(a['reasons']) or 'no flags'}) |",
        f"| Contributor | {rep.get('merged',0)} merged · {rep.get('closed',0)} closed · {rep.get('open',0)} open in this repo |",
        f"| Hypothesis graph | {'yes' if a['hypothesis_graph_present'] else 'no'} |",
        f"| Attestation | {a.get('attestation_path') or '—'} (sha verified: {a.get('attestation_sha256_verified')}) |",
        f"| Legibility | {a.get('legibility_verdict') or '—'} |",
        f"| Diff size | {f['diff_size_ratio']:.2f}× repo median |",
    ]
    return (
        "### immune scan\n\n"
        "| Check | Result |\n|---|---|\n"
        + "\n".join(rows)
        + "\n\n<sub>second-order receipt — see https://github.com/kimjune01/immune</sub>"
    )


# ---------------------------------------------------------------------------
# main


def _fetch_pr(pr: PR) -> dict | None:
    this_pr = gh(f"repos/{pr.slug}/pulls/{pr.number}")
    if not this_pr:
        print(f"could not fetch {pr.url}", file=sys.stderr)
    return this_pr


def cmd_filter(args: argparse.Namespace) -> int:
    """T0+T1: cheap mechanical filter + receipts presence/sha256.

    Never calls LLM, never runs sandbox. Output: pass | reject.
    """
    pr = parse_pr(args.pr)
    this_pr = _fetch_pr(pr)
    if not this_pr:
        return 2

    filter_r = run_filter(pr, this_pr)

    # T1: receipts presence + sha256 verification (no LLM)
    body = this_pr.get("body") or ""
    hg_present = attend_hypothesis_graph(body)
    att_path, att_sha_ok = attend_attestation(body)

    if att_path and att_sha_ok is False:
        filter_r.verdict = "reject"
        filter_r.reasons.append("attestation sha256 mismatch — fabricated or tampered")
    elif not hg_present and not att_path and filter_r.verdict == "pass":
        filter_r.verdict = "warn"
        filter_r.reasons.append("no receipts (no hypothesis graph, no attestation file)")

    verdict = "pass" if filter_r.verdict in ("pass", "warn") else "reject"

    receipt = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "action": "immune_filter",
        "pr": f"{pr.slug}#{pr.number}",
        "verdict": verdict,
        "stage": "t1-receipts" if verdict == "pass" else "rejected",
        "filter": asdict(filter_r),
        "receipts_present": {
            "hypothesis_graph": hg_present,
            "attestation_path": att_path,
            "attestation_sha256_verified": att_sha_ok,
        },
        "schema_version": "0.1",
    }

    if args.format == "json":
        json.dump(receipt, sys.stdout, indent=2)
        print()
    else:
        print(emit_filter_markdown(receipt))

    # Always exit 0 on successful run. The verdict is in the JSON; propagating
    # it through the exit code breaks `set -e` in the action wrapper, which
    # would mask labeling-as-reject as a workflow failure.
    return 0


def cmd_attend(args: argparse.Namespace) -> int:
    """T2+T3: LLM legibility + synthesis, optional test replay.

    Invariant: filter must have passed (caller is responsible for the
    label-gated invocation). This command does not re-check filter.
    """
    pr = parse_pr(args.pr)
    this_pr = _fetch_pr(pr)
    if not this_pr:
        return 2

    attend_r = run_attend(pr, this_pr)
    verdict_map = {
        "pass": "trusted",
        "warn": "suspect",
        "needs_human": "needs_human",
    }
    verdict = verdict_map.get(attend_r.verdict, "needs_human")

    receipt = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "action": "immune_attend",
        "pr": f"{pr.slug}#{pr.number}",
        "verdict": verdict,
        "stage": "verdict",
        "attend": asdict(attend_r),
        "schema_version": "0.1",
    }

    if args.format == "json":
        json.dump(receipt, sys.stdout, indent=2)
        print()
    else:
        print(emit_attend_markdown(receipt))

    # See cmd_filter: verdict is JSON-only; exit code is just success/failure
    # of the run itself (PR fetch, label API, etc).
    return 0


def emit_filter_markdown(receipt: dict) -> str:
    f = receipt["filter"]
    rp = receipt["receipts_present"]
    rep = f.get("contributor_reputation", {})
    rows = [
        f"| Verdict | **{receipt['verdict']}** |",
        f"| Stage | {receipt['stage']} |",
        f"| Duplicate | {f.get('duplicate_of') or '—'} (score {f['duplicate_score']:.2f}) |",
        f"| Contributor | {rep.get('merged',0)} merged · {rep.get('closed',0)} closed · {rep.get('open',0)} open in this repo |",
        f"| Diff size | {f['diff_size_ratio']:.2f}× repo median |",
        f"| AI policy | {f.get('ai_policy_violation') or 'clear'} |",
        f"| Hypothesis graph | {'yes' if rp['hypothesis_graph'] else 'no'} |",
        f"| Attestation | {rp.get('attestation_path') or '—'} (sha verified: {rp.get('attestation_sha256_verified')}) |",
        f"| Reasons | {', '.join(f['reasons']) or 'none'} |",
    ]
    return (
        "### immune filter (T0+T1)\n\n"
        "| Check | Result |\n|---|---|\n"
        + "\n".join(rows)
        + "\n\n<sub>cheap mechanical filter + receipts verification — no LLM call. https://github.com/kimjune01/immune</sub>"
    )


def emit_attend_markdown(receipt: dict) -> str:
    a = receipt["attend"]
    rows = [
        f"| Verdict | **{receipt['verdict']}** |",
        f"| Hypothesis graph (contributor) | {'yes' if a['hypothesis_graph_present'] else 'no'} |",
        f"| Attestation | {a.get('attestation_path') or '—'} (sha verified: {a.get('attestation_sha256_verified')}) |",
        f"| Test replay | {a.get('test_replay') or '—'} |",
        f"| Legibility | {a.get('legibility_verdict') or '—'} |",
        f"| Synthesis | {a.get('legibility_reason') or '—'} |",
        f"| Reasons | {', '.join(a['reasons']) or 'none'} |",
    ]
    hg_block = render_hypothesis_graph(a.get("hypothesis_graph_built"))
    return (
        "### immune attend (T2+T3)\n\n"
        "| Check | Result |\n|---|---|\n"
        + "\n".join(rows)
        + hg_block
        + "\n<sub>second-order receipt synthesized by SOTA model — https://github.com/kimjune01/immune</sub>"
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="immune", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    flt = sub.add_parser("filter", help="T0+T1: mechanical filter + receipts presence")
    flt.add_argument("pr", help="PR URL or owner/repo#N")
    flt.add_argument("--format", choices=["json", "markdown"], default="markdown")
    flt.set_defaults(func=cmd_filter)

    att = sub.add_parser("attend", help="T2+T3: LLM synthesis (assumes filter passed)")
    att.add_argument("pr", help="PR URL or owner/repo#N")
    att.add_argument("--format", choices=["json", "markdown"], default="markdown")
    att.set_defaults(func=cmd_attend)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
