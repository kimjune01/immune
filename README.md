# immune

**We're building `(PR) → merged`.**

That function. PR comes in, merge or close, with the maintainer's confidence calibrated by evidence the maintainer didn't have to produce themselves. Filter, test, reason are intermediate stages that exist only to make that transition cheap and trustworthy. Everything else is plumbing.

**Problem:** maintainers are overburdened reasoning through every PR — read the diff, check the description, decide if the contributor knows what they're doing. With AI-generated PRs, the queue grows without the contributor cost that used to act as a quality filter.

**Solution:** a Filter + Attend combo that runs in CI and produces **reasoning artifacts and quality attestations** the maintainer can scan in seconds. Filter is mechanical and cheap (duplicates, reputation, policy). Attend invokes a SOTA model (Sonnet possible, Opus recommended) to evaluate the receipts the contributor presented and synthesize a verdict. Maintainer reads a one-page comment instead of doing the reasoning themselves.

It's the inverse of [sweep](https://github.com/kimjune01/sweep): sweep produces receipt-attested PRs outbound; immune validates them inbound. **Same six-stage pipeline (per [The Natural Framework](https://june.kim/the-natural-framework)), opposite flow direction.** The symmetry is exact:

| sweep (outbound) | immune (inbound) |
|---|---|
| Perceive: scan repos for actionable issues | Perceive: receive incoming PR via webhook |
| Cache: TRIAGE_GRAPH per repo | Cache: PR + diff + linked attestation |
| Filter: ai-policy, body-count, org-saturation | Filter: duplicate, reputation, policy, receipts |
| Attend: hypothesis graph + adversarial volley | Attend: replay test, LLM synthesis |
| Consolidate: drip queue + retro params (append-only JSONL) | Consolidate: PR comment thread + label history (the PR list itself) |
| Transmit: PR with embedded receipts | Transmit: verdict label + synthesis comment |

What sweep produces, immune consumes. What immune accepts, the maintainer reviews. Each pipeline runs the same six morphisms; they compose end-to-end into a closed loop where receipts are produced under the same contract that validates them.

## Architecture

**This is kanban for code review.** Each PR is a card. Each label is a column. CI workflows pull cards forward when the upstream column has work; humans pull cards backward by removing labels. WIP limits are enforced by `immune:wip-*` locks (max one stage active per PR). The maintainer's GitHub PR list IS the board — sort by label, filter by column, see the work-in-progress at a glance. No Jira, no Trello, no separate dashboard.

**Four stages, ordered by cost.** Each stage short-circuits the next on `reject`. **CI triggers on labels** — the same labels humans add via the GitHub UI. **Agents and humans share the same interface.** A maintainer can manually add `immune:test-pending` to skip filter, or remove `immune:reject` to send a PR back through. An agent does the same thing via the API. There is no agent-only or human-only path — the labels are the protocol.

The Toyota Production System mapping is exact:

| TPS | immune |
|---|---|
| Pull system (downstream pulls from upstream) | Each stage triggers on the prior stage's label |
| Visible work-in-progress | Labels visible in GitHub UI |
| WIP limits | `immune:wip-<run-id>` lock, max 1 per PR |
| Stop the line on defect | Backflow via label removal |
| Continuous flow | PRs move at their own pace, no batching |
| Andon cord | Maintainer adds/removes any label, anytime |
| Kaizen | /retro tightens rules between cycles |

(For the categorically inclined: the stages compose as morphisms in the actor-model formalism — same structure, different vocabulary. Engineers should think kanban; theorists can read it as actors with label-keyed mailboxes.)

**No hidden state.** The PR list is the only inventory. immune writes no cache file, no reputation database, no local history. Every artifact is visible in GitHub's standard UI: labels, comments, PR metadata. Reputation lookups query the gh API live. The maintainer can audit the entire pipeline state by reading their PR list — no hidden table, no log file under `.github/`, no out-of-band record. **Anything immune knows, the maintainer can see.**

**No billing. No data leakage. Bring your own tokens.**

- **No billing.** immune is AGPL software running in your CI runner. There is no SaaS, no subscription, no per-PR fee, no usage tier. Anthropic charges you directly for the LLM tokens (~$0.01–$0.05/PR) at their published rates. We don't touch payment.
- **No data leakage.** Your PR contents (diffs, comments, attestations) are sent only to (a) the LLM provider behind the agent CLI you chose (`claude`, `codex`, or `gemini`) and (b) GitHub itself. Nothing is sent to a kimjune01-controlled endpoint. There is no telemetry, no analytics, no "improve our service" data collection. The action runs in your runner; it phones nowhere.
- **No Python deps.** immune.py imports only the stdlib. Every model call is `subprocess.run(...)` against a headless agent CLI you installed (`claude` / `codex` / `gemini`). No `pip install` of third-party libraries — the supply-chain surface is "what those CLIs depend on", which their maintainers audit.
- **Bring your own tokens.** `GITHUB_TOKEN` is the workflow's own token (default `${{ github.token }}`). The agent's credentials (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` / GCP service-account JSON / AWS creds) are your secrets, scoped to your repo. immune never sees, stores, or proxies credentials it didn't originate. If you revoke either token, immune stops working on the next run; there is no backdoor.

These are non-negotiable. The competitive landscape (devin, copilot enterprise, codiumai, greptile) all violate at least one. The trust gap is the wedge: maintainers will install a tool that runs in their own runner with their own keys before they install one that proxies their PRs through a third-party SaaS.

**FREE. Open source. Share-alike. Network-obligated.**

- **FREE** as in beer. No license fee, no premium tier, no "free for OSS" carve-out — there is no proprietary version to upsell to.
- **Open source** as in source. The whole stack is in this repo. Read it, fork it, audit it, modify it.
- **Share-alike.** Per AGPL-3.0 (code) and [CC-BY-SA-NS](https://june.kim/cc-by-sa-ns) (prose), derivatives carry the same license. Forks must publish under the same terms.
- **Network-obligated.** AGPL's defining clause: running a modified version *as a service* triggers source disclosure too, not just distributing a binary. A SaaS that wraps immune, tweaks it for their hosted offering, and serves it from their cloud must publish their fork. The cloud-loophole (use GPL code in a service without distributing the binary) doesn't apply here.

The combination is the point. MIT or Apache lets a competitor take the code, close-source their improvements, and ship a proprietary "immune Pro" — defeating the commons argument. GPL alone has the cloud loophole. AGPL closes it. The receipt-discipline pattern stays a commons whether it's installed as a CI action, wrapped in a cloud service, or repackaged for enterprise — every variant must remain readable and republishable.

This is the canon argument applied to infrastructure: copyleft on the orchestration layer means the orchestration commons compounds rather than fragments. Every successful imitator strengthens the commons rather than carving off a private piece of it.

```
filter ──→ test ──→ reason ──→ human judge
~free,ms   runner-min ~$0.01-$0.05  reads + decides
mechanical sandbox    LLM synthesis  merges or closes
dup,rep,   replays    legibility +
policy,    test_cmd   evidence
receipts
   ↓          ↓           ↓             ↓
reject?      fail?      suspect?     merge | close
immune:    immune:     immune:
reject     test-failed suspect
```

Each stage is ~10× more expensive than the prior. A PR rejected at filter costs nothing to clear; a PR that survives to reason costs cents; a PR that survives to human costs runner minutes plus cents. **Sedimentation is correct behavior at every stage** — most PRs should never reach reason, let alone human.

**Human is always the final stage.** immune labels and synthesizes; it never merges or closes by itself (unless `mode: gate` is set, in which case only filter `reject` auto-closes).

**Why test before reason:** the test result is the strongest signal the LLM can consume. Reason without test is guessing; reason with test is grounded synthesis. The order matters.

**Dry-run mode on any PR.** Add the label `immune:dry-run` to any PR (manually, in the GitHub UI) and the next pipeline run executes all stages but writes only to a single comment — no labels applied, no auto-close, no state changes. Used for tuning: a maintainer can flip dry-run on a known-good PR to see what immune would have said, adjust filter thresholds or model choice in their workflow file, then remove the label and re-run for real. Same actions, same code path, just suppressed side effects. Also lets a contributor see what immune will think before they push the actual PR — open as draft, label `immune:dry-run`, iterate.

**Race conditions are prevented by labels too.** Two workflows triggered simultaneously (e.g., a maintainer adds a label while CI is processing the same PR) could otherwise both apply contradictory verdict labels. immune avoids this with a distributed-lock pattern that uses labels as the lock substrate — same shape as the actor mailbox:

1. **Acquire.** At the start of each stage, the action atomically adds `immune:wip-<run-id>` (where `<run-id>` is the unique GitHub Actions run identifier). If any `immune:wip-*` label already exists on the PR, the action exits gracefully — another stage is mid-flight, this one waits for the next trigger.
2. **Work.** The stage does its checks while holding the WIP label.
3. **Release.** On success or failure, the action removes its `immune:wip-<run-id>` and applies the appropriate stage/verdict label. The release runs in a `trap` so even crashes release the lock.
4. **Flush.** A periodic flush workflow (`on: schedule: cron: '*/10 * * * *'`) scans the repo for `immune:wip-*` labels, checks the associated workflow run's status, and removes any whose run is no longer active (completed, failed, cancelled, or older than the runner timeout). Stale locks heal automatically within ~10 min without manual intervention.

The flush workflow is the *only* periodic process immune ships. Everything else is event-driven on labels. The lock substrate is labels (visible to humans), the lock identifier is the GitHub run ID (verifiable against the runs API), and the recovery mechanism is bounded-time flush. **No external lock service** (Redis, etcd, distributed mutex) — labels are sufficient because GitHub's label API is atomic per-PR.

**Test is itself a sub-pipeline.** Per [[feedback-implement-self-checks]], a TDD-shaped test commit can rubber-stamp the bug. Immune's test stage runs four substages, each of which is its own short-circuit:

| Substage | Check | Cheap reject |
|---|---|---|
| `test:present` | Are there test files in the diff at all? | yes if no |
| `test:tdd-shape` | Does the test fail on main and pass on branch? | yes if both legs same |
| `test:matches-issue` | Does the test assertion text mention the bug symptom from the linked issue? (string match, not coverage) | yes if assertion is unrelated |
| `test:assertion-not-trivial` | Does the test fail with an assertion error, not a setup/import error? | yes if test fails for the wrong reason |

Each substage labels independently. A PR with `test:tdd-shape` failing label tells the maintainer exactly where the receipt is weak — they don't have to read the code to know.

**Early exit means minimized cost.** A PR that fails `test:present` never spends runner minutes on the other three. A PR that fails the cheap mechanical filter never spends API budget on reason. The cost-per-PR is bounded by the cheapest stage that rejected it. Concretely: a duplicate PR costs ~$0; a no-receipts PR costs ~$0.001 (filter only); a fully-attested PR costs ~$0.01-$0.05 (full pipeline). Sedimentation at every stage is free; only the survivors pay.

### Action contracts

Each action obeys the same three rules: idempotent (running twice produces the same labels), label-gated (refuses to run without the right input label), and standalone (works without the others).

| Action | Input label | Output label | Refuses if |
|---|---|---|---|
| `filter` | (any PR) | `immune:test-pending` or `immune:reject` | another stage is mid-flight (WIP lock held) |
| `test` | `immune:test-pending` | `immune:reason-pending` or `immune:test-failed` | input label is missing (re-runs are safe) |
| `reason` | `immune:reason-pending` | `immune:trusted` / `immune:suspect` / `immune:needs-human` | input label is missing |

You can install `filter` only and skip the rest. You can install `reason` only and label PRs manually. The actions don't depend on each other's runtime — only on the labels.

### Backflow

Stages run forward by default but **the labels are bidirectional**. A maintainer (or agent) sends a PR back through the pipeline by removing the downstream label and adding an upstream one. Example flows:

| Maintainer action | Effect |
|---|---|
| Remove `immune:trusted`, add `immune:reason-pending` | Re-runs reason (e.g. after model upgrade) |
| Remove `immune:suspect`, add `immune:test-pending` | Re-runs test (e.g. CI environment changed) |
| Remove any label, add nothing | Stops the pipeline at this PR — manual judgment only |
| Add `immune:rerun-from-filter` | (Optional alias) — strips all immune labels, fires filter from scratch |

When a backflow happens, the action that fires marks `prior_gates_voided: true` in its receipt comment — same convention as sweep's [[feedback-attestation-proof]]. The new run doesn't inherit prior verdicts; it stands or falls on its own attestation. Ensures stale attestations don't laundry-launder into new verdicts.

**Symmetry holds in both directions.** Whether the label was added by an agent (forward) or removed by a human (backflow), the action that fires reads the same label state. There is no agent-only or human-only path; backflow is just forward dispatch with a reset.

### Label vocabulary

Labels are **terminal-only**. The four below are the entire vocabulary. State during the run is conveyed by GHA-native check_runs (visible in PR's "Checks" tab), not labels — maintainer attention is a real cost and we don't pay it for transient state.

| Label | Stage | Meaning | Maintainer filter |
|---|---|---|---|
| `immune:reject`  | filter (T0+T1) | failed mechanical checks (duplicate, AI-policy, missing receipts, attestation tampered); auto-closed in `gate` mode | sediment |
| `immune:trusted` | attend (T2+T3) | receipts present + verified + WHY-rationale clear | `is:open label:immune:trusted` — fast lane |
| `immune:suspect` | attend | passed filter; receipts thin, weak, or HG perturbations flagged risk — read the synthesis comment for the specific reason | slow lane |

There is NO `immune:needs-human` label. Anything the LLM would have escalated as "needs human" is either (a) a verifiable mechanical failure → `immune:reject` with the reason in the comment, or (b) a soft signal → `immune:suspect` with the reason in the comment. Hiding the reason behind a generic escalation label was making maintainers dig; surfacing it directly costs nothing.

The actor model still holds — each stage is a process, the PR is the mutable state — but the messages are the JOB DEPENDENCIES (GHA `needs:`) and CHECK STATUSES, not labels. Labels are reserved for what the maintainer wants to filter their PR list on.

If a maintainer wants the immune workflow to also gate the rest of their CI on `immune:reject` being absent, they add one line to their existing CI workflow's job(s):
```yaml
if: "!contains(github.event.pull_request.labels.*.name, 'immune:reject')"
```
Without that line, immune and the maintainer's CI run in parallel; attend's wait-for-CI loop ensures attend doesn't fire until CI is green.

## What it does

For each incoming PR, runs:

**Filter (cheap, ~seconds)** — mechanical checks that don't consume maintainer attention:
- Duplicate-detection: hash similarity vs recent merged/closed PRs
- Contributor reputation: per-repo merge/close/silent ratios
- Diff-size sanity vs repo norm
- AI-policy compliance (CONTRIBUTING.md, AGENTS.md)
- Body-count: bot-magnet issue detection

**Attend (writes the maintainer's reasoning for them, ~seconds)** — verifies the contributor's claims hold up and synthesizes a one-paragraph evaluation:
- Hypothesis-graph parser: did the contributor actually present one?
- Attestation file fetch + sha256 verify: cryptographic chain intact?
- Test replay: re-runs `test_cmd` from the receipt **only on PRs from the same repo** (not forks — see Security below). For forks, the test stage skips replay and labels `immune:test-skipped-fork` so the maintainer knows to evaluate the test results from CI manually.
- Legibility + synthesis: SOTA model (Opus recommended, Sonnet possible) reads the diff + receipts + test result and produces a one-paragraph "what this PR is, what evidence supports it, what the risk is" the maintainer can read in 30 seconds. Per-PR cost: ~$0.05 with Opus, ~$0.01 with Sonnet.

### Security: fork PRs and `test_cmd`

Running an arbitrary `test_cmd` from a fork PR is RCE on the maintainer's runner — the contributor controls the test file's contents *and* the command being run. By default, the test stage **does not replay tests on fork PRs**. The PR is labeled `immune:test-skipped-fork`, attend still runs (LLM reads diff + receipts + the contributor's claimed test results), and the maintainer makes the final call.

Maintainers who want fork-PR test replay (e.g. trusted-fork-only repos) can opt in via `replay-forks: true`. The test runs on `pull_request` (not `pull_request_target`), in a fresh runner, with secrets stripped. Even with opt-in, the recommendation is to gate test-replay-on-forks on a manual maintainer label (`immune:test-approved-by-maintainer`) so the maintainer reviews the test code before it executes.

This is the only stage with this asymmetry. Filter and reason are read-only on PR contents; only test executes contributor-controlled code.

Output: a synthesized verdict the maintainer can scan in 30 seconds instead of evaluating the PR for 20 minutes.

## What is a "receipt"?

A receipt is the contributor's structured claim that their fix is correct. Two kinds, both optional but valuable:

**1. Hypothesis graph in the PR body.** A short markdown block listing the hypotheses considered and their outcomes:

```markdown
## Hypothesis graph

H0: cache eviction races with read on macOS arm64. CONFIRMED — reproduced in test_cache_race.py.
H1: same race exists on Linux. KILLED — Linux uses different lock primitive (line 47).
H2: fix is to take exclusive lock around evict+read. CONFIRMED — H0 reproducer passes after patch.
```

**2. Attestation file linked from the PR body.** A separate text file (hosted in the contributor's fork or a paste service) that contains the verbatim test output, model review transcripts, and a sha256 the PR can be checked against:

```markdown
attestation_path: https://raw.githubusercontent.com/contributor/repo/branch/.attestation/issue-123.txt
attestation_sha256: 8eca2f0adf23a6ad5c21020b9ab85dd0fc5da0065aca660f77695f57ca2a76f8
```

immune fetches the file, hashes it, and refuses to advance if the hash doesn't match. Tampered or fabricated receipts fail the cryptographic chain.

Neither receipt is required — PRs without them go through filter and reason normally and just receive a `no-receipts` flag in the synthesis. The receipts make evaluation cheaper; their absence isn't an automatic reject.

## Why

Most OSS maintainers face a flooded queue with no quality filter beyond CI. Every PR that compiles enters the queue regardless of redundancy, contributor track record, or claim verifiability. Sorting by recency or notification mention isn't a filter; it's a coin flip with status anxiety.

immune installs the missing filter, plus a synthesis stage that does the maintainer's reasoning *for* them — reading the diff and any receipts the contributor presented and producing a one-paragraph verdict. The maintainer reads the paragraph, drills into anything suspicious, and decides.

When enough maintainers run a receipt-validating gate, contributor pipelines have an incentive to produce real receipts. The norm becomes self-enforcing.

## Install

Drop [`examples/minimal-workflow.yml`](examples/minimal-workflow.yml) into `.github/workflows/immune.yml`. Pick one `attend` block — the agent CLI it spawns is what runs the K=3 hypothesis-graph fan-out:

| `agent:` | CLI installed | Required secret(s) |
|---|---|---|
| `claude` | `@anthropic-ai/claude-code` (npm) | `anthropic-api-key`, OR Vertex (`use-vertex: '1'` + GCP creds), OR Bedrock (`use-bedrock: '1'` + AWS creds) |
| `codex` | `@openai/codex` (npm) | `openai-api-key` |
| `gemini` | `@google/gemini-cli` (npm) | `gemini-api-key` |

`agent:` can be left blank — auto-detects from which credentials are present (priority: codex if `OPENAI_API_KEY`, gemini if `GEMINI_API_KEY`, else claude).

Want a different agent CLI? Edit the install step to `npm install` your binary; `immune.py` will shell out to whatever `IMMUNE_AGENT` names. The three above are pre-wired because they're the popular drop-ins.

## CLI

```bash
pip install immune-receipts
immune scan https://github.com/owner/repo/pull/123
```

Outputs a JSON verdict + a markdown summary. Use locally to test against any open PR before installing the action.

## Verdicts

| Verdict | Meaning | Maintainer action |
|---|---|---|
| `trusted` | All filter + attend checks pass | Review like a known contributor |
| `suspect` | One or more attend checks fail | Read the diff carefully |
| `reject` | Filter checks fail (duplicate, policy, bot-magnet) | Auto-close or sediment |
| `needs_human` | Receipts present but unverifiable | Maintainer judgment call |

## Pipeline parallel

immune is the inverse of [sweep](https://github.com/kimjune01/sweep). Sweep produces receipt-attested PRs; immune validates them. Both run the same six-stage pipeline (per The Natural Framework) — sweep flows outbound, immune flows inbound. Together they close the loop: receipts are produced and consumed under the same contract.

## License

Dual: **code is AGPL-3.0**, **prose/specs/skills are [CC-BY-SA-NS](https://june.kim/cc-by-sa-ns)** (commercial OK, attribution required, derivatives carry the same license). Per [Canon](https://june.kim/canon), prose precise enough to compile to behavior is source code — so the spec prose is licensed as carefully as the executable. See `LICENSE` for the split.
