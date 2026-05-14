---
name: immunize
description: Install immune into one of your own forks. Elicits target if not given, detects the fork's language and CI conventions, previews the workflow file and secrets punch list, then on confirmation commits + pushes + opens two PRs — a rigorous install PR that immune must label trusted, and a deliberately weak canary PR that immune must label reject. The install attestation is the pair.
argument-hint: [local-fork-path] [--mode advisory|gate] [--agent claude|codex|gemini]
allowed-tools: Read, Write, Bash, Grep, AskUserQuestion
---

# Install immune in one of your forks

This skill installs immune into a fork **you own**, then proves the install worked by opening two PRs: one rigorous (immune must label `trusted`), one deliberately weak (immune must label `reject` or `suspect`). The pair of verdict labels IS the install attestation.

## Flow

```
elicit target → detect → render artifacts → PREVIEW + secrets punch list → CONFIRM
                                                                            ↓
                                  commit → push → labels → install PR (strong)
                                                        → canary PR (weak)
                                                        → watch labels
```

Preview-then-confirm is the default. There is no `--dry-run` flag because **the preview is always shown first**. The user types "go" / "ship it" to proceed; anything else aborts.

## Phase 0: Preflight

1. If `<local-fork-path>` is missing, **elicit** via AskUserQuestion. Suggest 3–5 forks under `~/Documents/` ranked by fewest existing workflows (single-workflow forks are easiest to canary).
2. `cd <local-fork-path>` — fail if not a directory.
3. `git rev-parse --git-dir` — fail if not a git repo.
4. `git remote get-url origin` — fail if origin is not owned by `gh api user --jq .login`.
5. `git status --porcelain` — refuse if working tree is dirty.
6. `gh auth status --show-token` — fail fast on auth issues. Inspect token scopes:
   - **Required**: `repo` (or fine-grained equivalent) and `workflow` (to push the workflow file).
   - **LOUD WARNING** if scopes include any `admin:*` (`admin:org`, `admin:repo_hook`, `admin:enterprise`, etc.) or other escalated permissions beyond what an installer needs. Print a banner and suggest the maintainer mint a fine-grained PAT scoped to exactly this repo with: `Pull requests: read+write`, `Contents: read+write` (just for branch push), `Issues: read+write` (for labels), `Workflows: read+write`. Provide the verification script (Phase E). Do not block — the maintainer is sophisticated enough to make the call.
7. Resolve `nameWithOwner` and default branch via `gh repo view --json nameWithOwner,defaultBranchRef`.

## Phase 1: Detection (parallel)

| Probe | Command | Tunes |
|---|---|---|
| Language | `gh api repos/$OWNER_REPO/languages --jq 'to_entries[0].key'` | replay default; sandbox image |
| Existing workflows | `ls .github/workflows/` | name collision (refuse if `immune.yml` exists) |
| AGENTS.md | local + `gh api repos/$OWNER_REPO/contents/AGENTS.md` | mode strictness; refuse if AI-prohibited |
| CONTRIBUTING.md | same | DCO/signed-commits flags |
| Existing labels | `gh api repos/$OWNER_REPO/labels --jq '.[].name'` | refuse if `immune:*` already present |
| Existing secrets | `gh secret list --repo $OWNER_REPO --jq '.[].name'` | which agent CLI's creds are already wired |
| GitHub token scopes | `gh auth status --show-token` | warn if `workflow` scope absent (can't push workflow files) |
| Solo / team | top contributor's % of commits | model default |
| Stars | `gh repo view --json stargazerCount` | model default |
| Closure rate | `gh pr list --state closed --search "is:unmerged"` ratio | mode default |

Cache to scratchpad — do not re-fetch.

## Phase 2: Inference (idempotent — re-running /immunize is safe)

The skill is **idempotent**: re-running it on a repo that's already installed should be a no-op (or upgrade), not a refusal. Each existing artifact is detected and reconciled, not duplicated.

| If | Then |
|---|---|
| `.github/workflows/immune.yml` exists with the current template's `kimjune01/immune/{filter,attend}@<current-version>` pin | **Skip workflow write**; report "already at version X" |
| `.github/workflows/immune.yml` exists pinned to an older version | **Offer upgrade**: render diff, ask before overwriting |
| `.github/workflows/immune.yml` exists but uses a hand-modified shape | **Diff and pause**: print the diff against the current template; let the user decide whether to overwrite |
| `immune:*` labels exist with `#EDEDED` color | **Skip label create** (idempotent) |
| `immune:*` labels exist with a different color | **Update color** (`gh label edit`) to `#EDEDED` |
| Branch `immune/codegen-strong` exists | **Skip strong code-gen**; reuse existing branch and ensure PR is open |
| Branch `immune/codegen-weak` exists | **Skip weak code-gen**; reuse existing branch and ensure PR is open |
| PR teaching comment already posted (detect by `### immune install — STRONG\|WEAK leg (teaching note)` prefix) | **Skip comment post**; or update if outdated |
| AGENTS.md prohibits AI contributions | **Refuse** |
| AGENTS.md mentions disclosure / quality-gate | `mode: gate`, `replay: true` |
| `closure_rate > 0.4` | `mode: gate` |
| Default | `mode: advisory` |
| `OPENAI_API_KEY` secret present | suggest `agent: codex` |
| `GEMINI_API_KEY` secret present | suggest `agent: gemini` |
| `ANTHROPIC_API_KEY` (or GCP/AWS for Vertex/Bedrock) | suggest `agent: claude` |
| None of the above | suggest `agent: claude`; flag punch list to set a key before workflows fire |
| Language is Rust / Go | `replay: true` |
| Language is Java / Maven / Gradle | `replay: false` |
| Language is Swift | `replay: false` |
| `--mode` / `--agent` flag passed | Overrides inference |

### Agent elicitation

After auto-suggesting, **always elicit** the final choice with `AskUserQuestion`:

> Which headless agent CLI should attend spawn? `claude` (Anthropic family — direct / Vertex / Bedrock), `codex` (OpenAI), or `gemini` (Google)?

The detected secrets are the suggestion order. The maintainer's answer is what gets baked into the workflow file as `agent: <name>`. AI-forward maintainers know these CLIs; the elicitation is a one-click confirmation, not a tutorial.

## Phase 3: Render artifacts (in memory only)

1. **Workflow file** — render `.github/workflows/immune.yml` from `examples/minimal-workflow.yml` with substitutions. Header comment lists every detection signal that fired and the knob it set.
2. **Label script** — `gh label create` per the immune vocabulary, one per line, `|| true` suffixed, idempotent.
3. **Code-gen agent briefs (STRONG + WEAK)** — two prompt templates that will be passed to the chosen agent CLI in Phase 6 to generate two real PRs against the fork. The pair IS the install attestation.
   - **STRONG brief**: "find a real bug or improvement in this codebase, fix it, ship the receipts: hypothesis graph + attestation file with sha256 + WHY rationale". Predicted verdict: `immune:trusted`.
   - **WEAK brief**: "make a real, mechanically-clean change with no receipts: no hypothesis graph, no attestation, body describes WHAT not WHY". Predicted verdict: `immune:suspect` (passes filter, fails attend).

## Phase 4: PREVIEW — show everything, then ask for confirmation

Print, in this order:

### A. Detection summary
```
Target:         <owner/repo>  (default branch: <name>)
Language:       <lang>
Existing wfs:   <list>
AGENTS.md:      <yes/no — short quote if relevant>
CONTRIBUTING:   <yes/no — DCO/signed-commits flags>
Closure rate:   <n%>  (over last 50 closed PRs)
Solo / team:    <solo|team>   (top contributor: <n%>)
Stars:          <n>
```

### B. Inferred knobs
```
mode:    <advisory|gate>          (← because <reason>)
agent:   <claude|codex|gemini>    (← because <reason>; confirmed via elicitation)
replay:  <true|false>             (← because <reason>)
hg-fanout: 3                       (default; 0 disables HG generation)
```

### C. Files to be inserted
```
NEW    .github/workflows/immune.yml      (<n> lines)
```

Then print the full workflow file in a fenced code block so the user can audit it.

### D. Labels to be created
Only THREE terminal labels (immune is minimal about state-as-labels):
- `immune:reject`  (filter — terminal)
- `immune:trusted` (attend — terminal)
- `immune:suspect` (attend — terminal)

No `immune:needs-human` — escalation should reveal the specific shortcoming in the synthesis comment, not hide behind a generic label.

**Color: all three use `#EDEDED`** (subtle gray). They group visually as "system labels" instead of competing with whatever loud labels the maintainer is already using for their own categorization. Semantic distinction lives in the name + the synthesis comment, not in screaming colors.

Print the `gh label create` script in a fenced code block, one line per label, color `EDEDED`, `|| true` suffixed:

```bash
gh label create immune:reject  --color EDEDED --description "filter T0+T1: failed mechanical checks" --repo <owner/repo> || true
gh label create immune:trusted --color EDEDED --description "attend T2+T3: receipts verified, fast-lane review" --repo <owner/repo> || true
gh label create immune:suspect --color EDEDED --description "attend: receipts thin or HG flagged risk; read the synthesis comment" --repo <owner/repo> || true
```

### E. Secrets / token punch list (PROMINENT)

This is the part the user must do before the workflow can run end-to-end. The required secret depends on the chosen `agent:`:

```
SECRETS REQUIRED ON <owner/repo> (depends on chosen agent):
  agent: claude   → ANTHROPIC_API_KEY
                    OR (Vertex)  GCP_SERVICE_ACCOUNT_JSON + project + location
                    OR (Bedrock) AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + region
  agent: codex    → OPENAI_API_KEY
  agent: gemini   → GEMINI_API_KEY

  Status of the relevant secret(s): <missing | present>
  Set via: gh secret set <NAME> --repo <owner/repo>

GITHUB TOKEN SCOPES (your local gh CLI):
  workflow            <STATUS: present | MISSING — required to push workflow files>
                       Refresh via: gh auth refresh -h github.com -s workflow
  repo                <STATUS: present | missing>
                       Refresh via: gh auth refresh -h github.com -s repo

REPO PERMISSIONS:
  Actions enabled?    <yes/no>     (Settings → Actions → Allow all actions)
  PR labels writable? <yes/no>     (workflow needs `pull-requests: write`)
```

If any required item is missing or unknown, **block confirmation** until the user confirms they've set them or explicitly accepts a degraded install (filter-only; attend will hard-fail until the secret is set).

#### Optional: fine-grained PAT verification script

If Phase 0 flagged the local gh token as over-scoped, provide this script for the maintainer to mint and verify a properly-scoped PAT:

```bash
# After minting at https://github.com/settings/tokens?type=beta
# (Repository access: kimjune01/<repo>; Permissions: Pull requests RW, Contents RW, Issues RW, Workflows RW)

export GH_TOKEN="github_pat_..."
gh api repos/<owner>/<repo> --jq .name                                  # contents:read
gh api repos/<owner>/<repo>/labels --jq '.[].name' | head                # issues:read
gh label create immune:test --color cccccc --repo <owner>/<repo> 2>&1   # issues:write
gh label delete immune:test --repo <owner>/<repo> --yes 2>&1            # issues:write (cleanup)
gh pr list --repo <owner>/<repo> --limit 1                              # pull_requests:read
# Pushing a branch tests contents:write; opening a PR tests pull_requests:write.
```

If all four commands succeed without permission errors, the PAT scope is right. Use that token for the install (export GH_TOKEN before re-running /immunize).

### F. Install demonstration (the attestation)

The install isn't "trust us, it works" — it's "watch immune label its own self-test PRs and see the verdicts come out as predicted". That's the demonstration.

```
SETUP (no PR — direct push to master, since this is your own fork):
  branch:   master
  files:    .github/workflows/immune.yml
  labels:   immune:* vocabulary (~9 labels)

PR 1 (STRONG code-gen, generated by chosen agent):
  branch:   immune/codegen-strong
  base:     <default-branch>
  shape:    real bug-fix or improvement, with hypothesis graph + attestation file (sha256 verified)
  predicted verdict: immune:trusted

PR 2 (WEAK code-gen, generated by chosen agent):
  branch:   immune/codegen-weak
  base:     <default-branch>
  shape:    real, mechanically-clean change, NO receipts, body describes WHAT not WHY
  predicted verdict: immune:suspect  (passes T0/T1 filter, fails T2 attend's receipt check)

The pair is the attestation: STRONG → trusted AND WEAK → suspect proves the
filter is calibrated from both sides. STRONG → not-trusted means too strict;
WEAK → trusted means too lenient. Either failure mode is visible in the
verdict, not buried.
```

### G. Confirmation prompt

Use AskUserQuestion: "Proceed with install? Reply `go` to commit + push + open both PRs, or `abort` to cancel." Until confirmed, no git ops, no remote calls.

## Phase 5: Setup (only after confirmation)

1. **Workflow direct-push to master** — for an own-fork install, no PR for the workflow itself; commit + push to default branch. (For an upstream install, this becomes a PR — out of scope for the canary flow.)
   - Write `.github/workflows/immune.yml`
   - `git add .github/workflows/immune.yml` + commit with HEREDOC message
   - `git push origin <default>`

2. **Labels** — execute the script from Phase 4D. Each line `|| true` (idempotent).

3. **Switch back** to whatever branch the user was on at preflight.

## Phase 6: Generate the attestation pair (code-gen PRs)

Spawn the chosen agent CLI twice in parallel — STRONG and WEAK — each in a fresh clone of the fork (`/tmp/<repo>-strong/`, `/tmp/<repo>-weak/`) so they don't stomp each other's git state. Each agent gets:

- The codebase (cloned)
- A brief from Phase 3
- Authority to push to its own branch and open a PR against `<default>`

**STRONG agent** generates a real bug-fix or improvement with full receipts (HG, attestation file, WHY rationale, sha256 chain). Predicted verdict: `immune:trusted`.

**WEAK agent** generates a real, mechanically-clean change without any receipts (no `## Hypothesis graph`, no `attestation_path:`, body describes WHAT). Predicted verdict: `immune:suspect`.

When both agents return, both PRs exist on the fork. The immune workflow fires on each `pull_request: opened` event and applies labels.

### Teaching comments (posted to each PR)

Right after each PR is created, post a teaching comment via `gh pr comment <N> --repo <owner/repo> --body "..."`. The comment lives on the PR forever; it's the maintainer's first encounter with immune's label vocabulary, anchored to a concrete example.

The comment shape (one per leg):

```markdown
### immune install — STRONG|WEAK leg (teaching note)

This PR is one of two that **`/immunize`** opened on this fork as the install attestation. **Expected verdict on this one: `immune:trusted`|`immune:suspect`.** Sister PR #N is the other leg.

**Why STRONG|WEAK:** <one paragraph explaining the receipts shape — full HG + attestation for STRONG; deliberately receiptless for WEAK; for WEAK note the model split (haiku) so weakness is organic, not instruction-shaped>.

#### immune label vocabulary (you'll start seeing these on every PR)

| Label | Stage | What it means |
|---|---|---|
| `immune:t1-pass`     | filter (T0+T1) | passed cheap mechanical checks — proceeds to attend |
| `immune:reject`      | filter | failed a cheap check; in `gate` mode also closes the PR |
| `immune:trusted`     | attend (T2+T3) | receipts present + verified + WHY clear — fast-lane |
| `immune:suspect`     | attend | passed filter but receipts thin or missing |
| `immune:needs-human` | attend | something off (e.g. attestation sha256 mismatch) |
| `immune:t0-pass` / `immune:t0-reject` | substage | rare; usually skipped to T1 |
| `immune:unknown`     | error | verdict computation failed; check the action run log |

#### Verify

`gh pr view <strong-N> --repo <owner/repo> --json labels --jq '.labels[].name'`
`gh pr view <weak-N>   --repo <owner/repo> --json labels --jq '.labels[].name'`

Action source: [kimjune01/immune@v0.2](https://github.com/kimjune01/immune) (AGPL-3.0). The action runs in your runner with your secrets; nothing is sent to a kimjune01-controlled endpoint.
```

The taxonomy table is the load-bearing part — it teaches the protocol the maintainer is about to be operating under. Per-PR placement (rather than a top-of-repo file) means the lesson is anchored to a concrete example forever, surfaces in PR scrollback, and doesn't pollute the maintainer's tree.

## Phase 7: Verification (the demonstration)

Print, **without writing any files to the target repo**:

```
Installed immune in <owner/repo>.

STRONG code-gen PR (expect immune:trusted): <url>
WEAK   code-gen PR (expect immune:suspect): <url>

Verify in ~2 min once workflows fire:

  STRONG (expect immune:trusted):
    gh pr view <strong-pr-num> --repo <owner/repo> --json labels --jq '.labels[].name'

  WEAK   (expect immune:suspect):
    gh pr view <weak-pr-num>   --repo <owner/repo> --json labels --jq '.labels[].name'
```

The convention IS the contract: `immune/codegen-strong` → `immune:trusted`, `immune/codegen-weak` → `immune:suspect`. Maintainer eyeballs the labels. No files are committed to the target repo for this purpose — install-level meta lives in the maintainer's terminal output, not their git history.

Per-PR attestation files (e.g. `.immune/codegen-strong-attestation.txt` on the strong branch) DO live in the contributor's branch — they're load-bearing receipts that immune fetches and sha256-verifies. If the maintainer merges a strong PR, that attestation lands in master; squash-merging or excluding the path on merge is the maintainer's call. (The receipts are useful provenance even after merge; not pollution.)

The verdict pair is the proof:

| STRONG verdict | WEAK verdict | What it means |
|---|---|---|
| `trusted` | `suspect` | **Calibrated**. Install attested. |
| `suspect` or `reject` | anything | Filter/attend too strict. STRONG should pass; tighten the agent brief or the reject criteria. |
| `trusted` | `trusted` | Filter too lenient. WEAK shouldn't pass attend. Tighten attend's receipt check or downgrade legibility threshold. |
| `reject` | `reject` | Both legs failing — likely the workflow itself isn't running. Check Actions tab on the fork. |

## Phase 8: Iteration loop

Both PRs sit on branches you control. To iterate:

1. Edit on the relevant branch (workflow file, agent brief, or PR body)
2. `git push` — fires `pull_request: synchronize`, workflow re-runs
3. Watch labels
4. Repeat

Once verdicts match predictions, the install is attested. Leave the PRs open as a permanent regression test or close them. Either way, the workflow continues running on every future PR — including ones that aren't from this install pipeline.

## Refusal cases

Refuse hard:
- Path is not a git repo, or origin is not owned by you
- Working tree is dirty
- AGENTS.md prohibits AI contributions outright
- `gh` CLI lacks `workflow` scope (would block the push)

Do NOT refuse on:
- Existing `.github/workflows/immune.yml` — diff and reconcile (Phase 2 idempotency table)
- Existing `immune:*` labels — reuse, recolor if needed
- Existing `immune/codegen-{strong,weak}` branches or PRs — reuse, refresh
- Existing teaching comments — skip or update

Re-running `/immunize` on an already-installed repo should be a safe no-op. The exit message is "already installed at version X; verify with: ..." rather than an error.

## Why a skill, not a script

The install is judgment work. Every fork's right configuration depends on its language, CI surface, contributor density, AI-policy posture, and your intent for upstreaming. Encoding inference rules as prose-that-compiles (per [Canon](https://june.kim/canon)) means they can be improved by editing this file, not by shipping a new release.

The two-PR canary is the load-bearing design choice: an install that only opens an "expect trusted" PR can hide a too-lenient filter, and an install that only opens an "expect reject" PR can hide a too-strict filter. Both PRs together pin the filter from both sides. Per [[feedback-attestation-universal]], every change needs a receipt — for an install, the receipt is the verdict pair.

## Related

- [README](../README.md) — what immune is and the four stages
- `examples/minimal-workflow.yml` — the template Phase 3 renders from
- [[feedback-skill-hardlinks]] — `~/.claude/skills/immunize/skill.md` must be a hardlink to this file
- [[feedback-attestation-universal]] — every change needs a receipt; install attestation is the verdict pair
- [[feedback-attestation-proof]] — verdicts must be sub-minute checks, not opinions
