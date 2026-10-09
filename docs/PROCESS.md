# Process — from investigation to pull request

The method followed for any non-trivial change, code or docs. Every change, even a small one,
still goes through the independent audit before it is pushed. The owner signs off at each
**gate**; implementation flows straight into the audit. The audit has its own reference,
[PROCESS_AUDIT](PROCESS_AUDIT.md), not duplicated here.

```
1. Investigation → 2. /grill-me → 3. Plan Mode → 4. Implementation
→ 5. Independent audit until SAFE → 6. Pull request
```

## 1. Investigation — no changes

- **Status quo**: what the code actually does today, on an up-to-date `origin/main` (a local
  checkout may lag behind) — the real call sites, `AGENTS.md`, and what the listing commands
  print (`cx`, `ccx`, `cx json`, `ccx json`: not read-only — they refresh the active account's
  saved copy and ccx's usage cache, as the app does — but safe to run).
- **Strategy**: the possible options compared on effort, risk, impact and maintenance, with a
  recommendation for the **simplest** good one — not the first that works.
- Live data that the repo can't show (an account's plan, a provider's API behavior) is checked
  read-only or asked to the owner.
- **Deliverable**: findings, options, recommendation, open questions.
- **Gate**: the owner validates the findings and the strategy, and starts the grill.

## 2. `/grill-me` — review before the plan

(`/grill-me` in Claude Code; in Codex, ask for the `grill-me` skill.)

What gets reviewed is the **strategy recommended by the investigation**; the written plan only
exists at step 3.

- Start with **BIG or SMALL change?** BIG: up to 4 issues per section. SMALL: one question per
  section.
- Then four sections, in order:
  1. **Architecture** — boundaries between the app, `cx`/`ccx`, the status line and the
     installer; data flow; what is shared with Claude Code, Codex and the Keychain.
  2. **Code quality** — repetition, error handling, missing edge cases, over- or
     under-engineering.
  3. **Verification** — there is no test suite: what will prove the change works (commands to
     run, states to reproduce, screenshots), and which failure modes stay unchecked.
  4. **Performance & energy** — polling, process spawns, Keychain calls, rate-limited endpoints
     (`/api/oauth/usage` answers 429 when polled too often).
- One section at a time, pausing after each. Issues are **numbered**, options **lettered**, each
  option repeats its number and letter, the recommendation is always the first option, with its
  concrete trade-offs.
- What the code can answer is explored, not asked.
- **Deliverable**: a table of the decisions taken.
- **Gate**: the owner's answers ARE the decisions; the owner starts Plan Mode.

## 3. Plan Mode — the final plan

- The plan follows from the grill's answers; it doesn't reopen them.
- Contents: context, branch, files touched, commits in order, what is reused, end-to-end
  verification (including the audit).
- **Gate**: the owner approves the plan.

## 4. Implementation

- Branch from up-to-date `origin/main` (or stacked on an open PR when it depends on it). Commits
  stay **local**: nothing is pushed.
- Behavior the owner did not ask to change stays unchanged; no rewrite as a side effect.
- Docs describing a change live in the same commit as the change (`README.md`, `AGENTS.md`).
- Pre-flight: `tools/check.sh` must end with `check: OK` — run that exact command, not a
  paraphrase of it.
- No gate: the audit starts as soon as the local commits are ready.

## 5. Independent audit until SAFE

- Protocol: [PROCESS_AUDIT](PROCESS_AUDIT.md); operating mode: skill
  [`independent-audit`](../.claude/skills/independent-audit/SKILL.md).
- Every finding is settled and every settling commit re-audited, until a SAFE verdict on the
  last delta.
- **Gate**: the SAFE verdict and the list of findings are shown to the owner, who gives (or not)
  the go to push.

## 6. Pull request

- Push and open the PR **only** after the audit is settled and the owner's go.
- The PR description says what changed, how it was verified, what the audit found and how each
  finding was settled, and any known limit.
- **Gate**: merge on the owner's say only. Stacked PRs are merged in order.
