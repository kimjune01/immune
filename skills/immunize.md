---
name: immunize
description: Install immune into one of your own forks. Elicits target if not given, detects the fork's language and CI conventions, previews the workflow file and secrets punch list, then on confirmation commits + pushes + opens two PRs — a rigorous install PR that immune must label trusted, and a deliberately weak canary PR that immune must label reject. The install attestation is the pair.
argument-hint: [local-fork-path] [--mode advisory|gate] [--model sonnet|opus]
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
6. `gh auth status` — fail fast on auth issues.
7. Resolve `nameWithOwner` and default branch via `gh repo view --json nameWithOwner,defaultBranchRef`.

## Phase 1: Detection (parallel)

| Probe | Command | Tunes |
|---|---|---|
| Language | `gh api repos/$OWNER_REPO/languages --jq 'to_entries[0].key'` | replay default; sandbox image |
| Existing workflows | `ls .github/workflows/` | name collision (refuse if `immune.yml` exists) |
| AGENTS.md | local + `gh api repos/$OWNER_REPO/contents/AGENTS.md` | mode strictness; refuse if AI-prohibited |
| CONTRIBUTING.md | same | DCO/signed-commits flags |
| Existing labels | `gh api repos/$OWNER_REPO/labels --jq '.[].name'` | refuse if `immune:*` already present |
| Anthropic key | `gh secret list --repo $OWNER_REPO --jq '.[].name'` | filter-only fallback if missing |
| GitHub token scopes | `gh auth status --show-token` | warn if `workflow` scope absent (can't push workflow files) |
| Solo / team | top contributor's % of commits | model default |
| Stars | `gh repo view --json stargazerCount` | model default |
| Closure rate | `gh pr list --state closed --search "is:unmerged"` ratio | mode default |

Cache to scratchpad — do not re-fetch.

## Phase 2: Inference

| If | Then |
|---|---|
| `.github/workflows/immune.yml` exists | **Refuse** |
| Any `immune:*` label exists | **Refuse** unless `--force` |
| AGENTS.md prohibits AI contributions | **Refuse** |
| AGENTS.md mentions disclosure / quality-gate | `mode: gate`, `replay: true` |
| `closure_rate > 0.4` | `mode: gate` |
| Default | `mode: advisory` |
| Solo maintainer (top > 80%) | `model: sonnet` |
| Team repo with `> 1k` stars | `model: opus` |
| No `ANTHROPIC_API_KEY` secret | Install filter only; comment out attend job; flag in punch list |
| Language is Rust / Go | `replay: true` |
| Language is Java / Maven / Gradle | `replay: false` |
| Language is Swift | `replay: false` |
| `--mode` / `--model` flag passed | Overrides inference |

## Phase 3: Render artifacts (in memory only)

1. **Workflow file** — render `.github/workflows/immune.yml` from `examples/minimal-workflow.yml` with substitutions. Header comment lists every detection signal that fired and the knob it set.
2. **Label script** — `gh label create` per the immune vocabulary, one per line, `|| true` suffixed, idempotent.
3. **Install PR body (strong)** — carries the receipts that immune itself reads:
   - Hypothesis graph (H0: install file is well-formed; H1: workflow triggers on the right events; H2: stages compose; etc., each with verification)
   - Attestation: workflow was rendered from template + detection signals (cite the signal table)
   - Self-prediction: "this PR should be labeled `immune:trusted`"
4. **Canary PR diff and body (weak)** — a deliberately receiptless PR designed to fail immune. Default canary is a one-character whitespace tweak in `README.md`:
   - Empty body
   - No linked issue
   - No hypothesis graph
   - No tests
   - Self-prediction: "this PR should be labeled `immune:reject` or `immune:suspect`"

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
mode:    <advisory|gate>     (← because <reason>)
model:   <sonnet|opus>       (← because <reason>)
replay:  <true|false>        (← because <reason>)
```

### C. Files to be inserted
```
NEW    .github/workflows/immune.yml      (<n> lines)
```

Then print the full workflow file in a fenced code block so the user can audit it.

### D. Labels to be created
List the 7 labels; print the `gh label create` script in a fenced code block.

### E. Secrets / token punch list (PROMINENT)

This is the part the user must do before the workflow can run end-to-end:

```
SECRETS REQUIRED ON <owner/repo>:
  ANTHROPIC_API_KEY   <STATUS: missing | present>
                       Set via: gh secret set ANTHROPIC_API_KEY --repo <owner/repo>
                       Without it, the attend stage is skipped (filter-only install).

GITHUB TOKEN SCOPES (your local gh CLI):
  workflow            <STATUS: present | MISSING — required to push workflow files>
                       Refresh via: gh auth refresh -h github.com -s workflow
  repo                <STATUS: present | missing>
                       Refresh via: gh auth refresh -h github.com -s repo

REPO PERMISSIONS:
  Actions enabled?    <yes/no>     (Settings → Actions → Allow all actions)
  PR labels writable? <yes/no>     (workflow needs `pull-requests: write`)
```

If any required item is missing or unknown, **block confirmation** until the user confirms they've set them or explicitly accepts a degraded install.

### F. PRs that will be opened
```
PR 1 (install, strong):
  branch:   immune/install
  base:     <default-branch>
  title:    immune: install filter+attend gate
  receipts: hypothesis graph + attestation in body
  expected verdict: immune:trusted

PR 2 (canary, weak):
  branch:   immune/canary-weak
  base:     <default-branch>
  title:    docs: trim trailing whitespace in README
  receipts: NONE (deliberately)
  expected verdict: immune:reject (or immune:suspect in advisory mode)
```

### G. Confirmation prompt

Use AskUserQuestion: "Proceed with install? Reply `go` to commit + push + open both PRs, or `abort` to cancel." Until confirmed, no git ops, no remote calls.

## Phase 5: Execute (only after confirmation)

1. **Branch + commit (install)**
   - `git checkout -b immune/install` (refuse if exists)
   - Write `.github/workflows/immune.yml`
   - `git add` + commit with HEREDOC message that mirrors the install PR body's receipt summary
   - `git push -u origin immune/install`

2. **Labels** — execute the script from Phase 4D. Each line `|| true` (idempotent).

3. **Install PR** — `gh pr create --base <default> --head immune/install --title "..." --body "<install PR body>"`.

4. **Canary branch + commit**
   - `git checkout <default>` (or `git fetch origin <default>`)
   - `git checkout -b immune/canary-weak`
   - Apply the canary diff (e.g. `sed -i '' 's/ $//' README.md` if there's trailing whitespace, else add and remove a single space)
   - Commit with empty body, terse subject only
   - `git push -u origin immune/canary-weak`

5. **Canary PR** — `gh pr create --base <default> --head immune/canary-weak --title "docs: trim trailing whitespace" --body ""`.

6. **Switch back** to whatever branch the user was on at preflight.

## Phase 6: Verification

Print:

```
Installed immune in <owner/repo>.

Install PR (expect immune:trusted):  <url>
Canary PR (expect immune:reject):    <url>

Watch with:
  gh pr view <install-url> --json labels,statusCheckRollup
  gh pr view <canary-url>  --json labels,statusCheckRollup

Wait ~2 min for the workflows to fire, then re-check. Report back.
```

If both labels match expectations, the install is attested. If either fails:
- **Install labeled reject/suspect** → bug in immune's filter or the install PR's receipts; iterate on the install PR's body or the workflow file
- **Canary labeled trusted** → immune's filter is too lenient; tighten the inferred mode or the action's reject criteria

## Phase 7: Iteration loop

Both PRs sit on branches you control. To iterate:

1. Edit on the relevant branch (`.github/workflows/immune.yml` for the workflow itself; PR body via `gh pr edit` for receipts)
2. `git push` — fires `pull_request: synchronize`, workflow re-runs
3. Watch labels
4. Repeat

When both verdicts match expectations, merge the install PR. Close the canary (or leave open as a permanent low-priority regression test).

## Refusal cases

Refuse hard:
- Path is not a git repo, or origin is not owned by you
- Working tree is dirty
- `.github/workflows/immune.yml` already exists
- Any `immune:*` label already exists (without `--force`)
- AGENTS.md prohibits AI contributions outright
- `gh` CLI lacks `workflow` scope (would block the push)

## Why a skill, not a script

The install is judgment work. Every fork's right configuration depends on its language, CI surface, contributor density, AI-policy posture, and your intent for upstreaming. Encoding inference rules as prose-that-compiles (per [Canon](https://june.kim/canon)) means they can be improved by editing this file, not by shipping a new release.

The two-PR canary is the load-bearing design choice: an install that only opens an "expect trusted" PR can hide a too-lenient filter, and an install that only opens an "expect reject" PR can hide a too-strict filter. Both PRs together pin the filter from both sides. Per [[feedback-attestation-universal]], every change needs a receipt — for an install, the receipt is the verdict pair.

## Related

- [README](../README.md) — what immune is and the four stages
- `examples/minimal-workflow.yml` — the template Phase 3 renders from
- [[feedback-skill-hardlinks]] — `~/.claude/skills/immunize/skill.md` must be a hardlink to this file
- [[feedback-attestation-universal]] — every change needs a receipt; install attestation is the verdict pair
- [[feedback-attestation-proof]] — verdicts must be sub-minute checks, not opinions
