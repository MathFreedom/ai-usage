# Process — independent, non-oriented audit before merge

Every change, code or docs, small or not, goes through this audit before it is pushed (the full
method of [PROCESS](PROCESS.md) — investigation, grill, plan — is for non-trivial changes). Adapted for a project
without CI or test suite: the proof is execution, and `tools/check.sh` is the shared pre-flight.

## Cardinal rules

1. **No merge without an audit.** "It builds" proves the code compiles, not that the change does
   what it claims, nor that it breaks nothing else.
2. **Every finding is settled before merge** — no audit debt. If the verdict is NOT SAFE: fix,
   then re-audit the delta.
3. **Any commit added after the audit is unaudited.** A settling commit, an amend, a rebase that
   needed conflict resolution: the delta since the audited state is audited again.
4. **Push and PR happen only after the settled audit** and the owner's go. Order: local commit →
   audit (on the local commit) → settle findings (+ re-audit of the delta) → push + PR → merge.

## The auditor: what they get, what they don't

| They GET | They DON'T get |
|---|---|
| The **diff** (`git diff <base>..<branch>`) | The commit message body |
| Minimal repo context (`AGENTS.md`, how to run `tools/check.sh`) | The **justification** of the design |
| **The concrete objective**: what must be TRUE once the change is in, in factual, checkable sentences | The plan, or the reasoning that led to this form of fix |
| | The findings already known |

Without the objective, an auditor can only look for generic defects and can't answer the one
question that matters: **does this change do what it claims?** The justification is withheld
because an auditor who reads the author's reasoning checks that reasoning and inherits its blind
spots; they must establish by their own means whether the objective is met, and remain free to
report defects unrelated to it.

*Shape of the objective — factual and falsifiable, never explanatory:*
> ✅ "After this change, `cx use <name>` makes new `codex` sessions use `<name>`, even when the
> Codex app-server daemon was already running."
> ❌ "This change restarts the daemon because it caches auth in memory."

## How the auditor works

- In a **throwaway detached worktree**, never in the author's checkout:
  `git worktree add --detach /tmp/wt-audit-<name> <branch>` … `git worktree remove --force` at the end.
- **Proof by execution** whenever feasible (temporary script or build, run, then deleted); a
  line of reasoning never beats an execution.
- `tools/check.sh` must end with `check: OK` in the worktree.
- **Never touches the owner's real data**: no `cx`/`ccx` `use`, `add`, `save` or `rm`, no change
  to `~/.codex`, `~/.claude.json`, `~/.claude/settings.json`, no `install.sh`. Listing commands
  (`cx`, `ccx`, `cx json`, `ccx json`) are not read-only — they refresh the active account's own
  saved copy and the usage cache, as the app does every 10 minutes — but they are safe to run.
  Anything else that writes runs with a temporary `HOME`.
- Reports each finding with file:line, a concrete failing scenario, and the minimal fix, ranked
  by severity — or says plainly that the diff is fine.
- Verdict: **SAFE** or **NOT SAFE**.

## Arbitration

| Situation | Decision |
|---|---|
| Confirmed, with a reproducible scenario | Fixed before going further |
| Confirmed but not reachable in real use | Noted in the PR (or `AGENTS.md` "Ideas / not done"), not patched |
| Disputed by the author | **Blind double check**: two independent verifiers, one told to PROVE it, the other to REFUTE it, neither seeing the other's verdict; both must try to reproduce it. The owner decides if they disagree. |
| Refuted | Dropped, with the reason written in the PR |

## Lessons to keep

1. Before a commit whose message lists fixes: `git diff --staged --name-only` and a grep of the
   key content, compared with the announced list. A commit that lies about its content poisons
   the whole history.
2. The pre-flight is **one command**, `tools/check.sh`, run as is — a paraphrase drifts silently
   and keeps returning "fine".
3. Never restore files with a broad `git checkout --` or `stash`: it also wipes uncommitted edits.
   Commit first.

## Exit criteria

No confirmed finding left · `check: OK` on the audited commit · delta since the audit empty or
re-audited · the owner has seen the verdict.
