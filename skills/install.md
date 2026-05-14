---
name: immune-install
description: Customize the immune actions for a target repo and write the installed workflow file. Reads the repo's language, CI conventions, AGENTS.md/CONTRIBUTING.md tone, and prior PR-closure patterns. Emits a workflow file that fits the repo, plus a punch list of secrets and labels the maintainer needs to set up.
argument-hint: <owner/repo>
allowed-tools: Read, Write, Bash, Grep
---

# Install immune in a target repo

Don't drop a generic workflow file into someone's repo. Read the repo first, infer the right knobs, write a customized `.github/workflows/immune.yml` that matches the repo's language, conventions, and maintainer posture. The output is a PR (or a manual-install instruction) the maintainer can review.

## Inputs

A `<owner/repo>` argument. The skill clones (or `gh api`-reads) the repo and inspects:

| Signal | Where to find it | What it tunes |
|---|---|---|
| Language | top language via `gh api repos/X/languages` | `test` stage build commands; sandbox image |
| CI provider | `.github/workflows/*` presence | placement and naming of immune.yml |
| Existing labels | `gh api repos/X/labels` | label namespace collisions; reuse `bug`/`good first issue` if present |
| AGENTS.md | `gh api repos/X/contents/AGENTS.md` | strictness — anti-AI repo gets `mode: gate`, neutral repo gets `advisory` |
| CONTRIBUTING.md | same | DCO, signed-commits, target-branch rules → mirror in filter checks |
| Prior closure rate | `gh pr list --state closed --search "is:unmerged"` | high closure rate → start in `gate` mode; low → `advisory` |
| Maintainer count | `gh api repos/X/contributors` | solo maintainer → recommend Sonnet (cost-conscious); team → Opus OK |
| Anthropic key check | `gh secret list --repo X` | warn if `ANTHROPIC_API_KEY` not set |
| Existing immune labels | `gh api repos/X/labels` | warn on collision; suggest namespace adjustment |

## Process

### Phase 0: Preflight

1. `gh auth status` — fail fast on auth issues.
2. `gh api repos/<owner>/<repo>` — verify the repo exists and you can read it.
3. Refuse if `repo.archived` is true, or if `disabled_at` is set. Archived repos shouldn't get new infrastructure.

### Phase 1: Detection

Run all detection probes in parallel (each is one API call):
- `repo_lang = gh api repos/X/languages | jq 'to_entries[0].key'`
- `has_agents = gh api repos/X/contents/AGENTS.md` (true if 200)
- `has_contributing = gh api repos/X/contents/CONTRIBUTING.md` (true if 200)
- `existing_labels = gh api repos/X/labels --jq '.[].name'`
- `existing_workflows = gh api repos/X/contents/.github/workflows --jq '.[].name'`
- `solo_maintainer = (gh api repos/X/contributors | jq '[.[] | .contributions]' | first vs second ratio > 0.8)`
- `closure_rate = (closed_unmerged_count / (closed_count + merged_count)) over last 50 PRs`

Cache results to a scratchpad — don't re-fetch.

### Phase 2: Inference

| If | Then |
|---|---|
| AGENTS.md mentions blanket AI prohibition | **Don't install.** Print: "this repo prohibits AI contributions; immune installation would violate AGENTS.md. Recommend the maintainer install it themselves." |
| AGENTS.md mentions disclosure or quality-gate language | `mode: gate`, `replay: true` |
| closure_rate > 0.4 | `mode: gate` (high-noise queue benefits from auto-close) |
| solo_maintainer | `model: sonnet` (cost-conscious default) |
| team repo with > 1k stars | `model: opus` (synthesis quality matters more than cost) |
| no `ANTHROPIC_API_KEY` secret | Skip the `reason` stage; install filter-only first; warn the maintainer |
| `immune:*` labels already exist | Suggest the maintainer rename them; don't overwrite |
| Repo language is Swift | Add `xcode-select --install` step note in workflow comments |
| Repo language is Rust | Set `replay: true`; cargo test is reproducible |
| Repo language is Java/Maven/Gradle | Set `replay: false`; build times often exceed runner budget |

### Phase 3: Generate workflow file

Render `.github/workflows/immune.yml` from the template (`examples/minimal-workflow.yml` in this repo) with the inferred parameters substituted. Comment in the generated file:
- which detection signals fired
- which knobs they set
- how to flip mode/model later

The generated file should be self-explanatory enough that the maintainer can audit it before merging.

### Phase 4: Generate label scaffolding

Write a one-shot bash script the maintainer can run:

```bash
gh label create "immune:test-pending" --color FBCA04 --description "Filter passed; queued for sandbox test" --repo X
gh label create "immune:reason-pending" --color 0E8A16 --description "Test passed; queued for LLM synthesis" --repo X
gh label create "immune:trusted" --color 0E8A16 --description "All immune stages passed" --repo X
gh label create "immune:suspect" --color D93F0B --description "Read carefully — receipts incomplete or LLM flagged risk" --repo X
gh label create "immune:needs-human" --color B60205 --description "Escalation: attestation tampered or novel pattern" --repo X
gh label create "immune:reject" --color 333333 --description "Failed cheap filter; auto-closed in gate mode" --repo X
gh label create "immune:test-failed" --color D93F0B --description "Sandbox test replay failed" --repo X
```

Reuse existing colors if the repo already has a color convention.

### Phase 5: Output

Three artifacts:
1. **PR description** — the customized workflow file, ready to commit
2. **Punch list** — what the maintainer must do manually:
   - Set `ANTHROPIC_API_KEY` secret (or accept filter-only)
   - Run the label-creation script
   - Decide on mode (advisory recommended for first 7 days)
3. **Verification command** — how to test it works:
   ```bash
   immune filter <owner/repo>#<recent-pr> --format markdown
   ```

If the user is the repo owner, optionally offer to open the install PR directly via `gh pr create`. Otherwise print the workflow file and the punch list to stdout.

## Output format

The skill prints (in this order):

1. Detection summary — what it found about the repo
2. Inferred knobs — what those signals translated to
3. Generated `.github/workflows/immune.yml` content (in a fenced code block)
4. Label-creation script (in a fenced code block)
5. Punch list of manual steps

Don't auto-commit. The skill produces the artifacts; the maintainer reviews and applies. Per [[feedback-attestation-universal]], every change needs a receipt — installation is no exception.

## Refusal cases

Always refuse to install when:
- Repo is archived or disabled
- AGENTS.md prohibits AI contributions outright
- Repo is owned by a known anti-pipeline organization (cross-reference local banlist if available)
- Maintainer hasn't acknowledged the install (e.g. running this skill on a stranger's repo without invitation)

The install is an invasive change — adding workflows, labels, secret expectations. Get the maintainer's blessing first.

## Why a skill, not a script

The install is judgment work — every repo's right configuration is different, and the inference rules in Phase 2 will keep growing as we learn what works. Encoding it as prose-that-compiles (per [Canon](https://june.kim/canon)) means the install behavior can be improved by editing prose, not by shipping a new release. The same skill, run on different repos, produces different artifacts. That's the point.
