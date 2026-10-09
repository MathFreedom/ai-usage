---
name: independent-audit
description: Run the mandatory independent, non-oriented audit of a local branch before it is pushed (code or docs) — throwaway worktree, objective without justification, proof by execution, findings settled, delta re-audited. Use before any push or PR in this repo.
---

# Independent audit before push — operating mode

**The protocol of record is [docs/PROCESS_AUDIT.md](../../../docs/PROCESS_AUDIT.md)** (cardinal
rules, what the auditor gets, arbitration, lessons). This is the condensed sequence.

1. **Commit first**, locally. Do **not** push, do **not** open the PR: the audit works on the
   local commit.
2. Write the **objective**: what must be TRUE once the change is in, in factual, falsifiable
   sentences. Never the justification, the plan, or known findings.
3. Launch an auditor agent with: the repo path, the local branch, the diff base, the objective,
   and the instructions to work in a throwaway detached worktree
   (`git worktree add --detach /tmp/wt-audit-<name> <branch>`), run `tools/check.sh` there, prove
   by execution, never touch the owner's real accounts or settings (temporary `HOME` for anything
   that writes), remove the worktree, and answer SAFE or NOT SAFE with ranked findings
   (file:line, failing scenario, minimal fix).
4. **Settle every finding** (fix, or arbitrate per the protocol — blind double check only for a
   disputed one). Before committing the fixes, compare `git diff --staged` with the list you
   announce.
5. **Re-audit the delta** added after the audit (settling commits, amends, conflict-resolving
   rebases) with the same rules, until SAFE.
6. Show the owner the verdict and the findings. **Push + PR only on the owner's go.**

## Docs-only diff

The proof by execution is checking every factual claim the diff introduces against the code,
git and GitHub (commands, paths, file names, behaviors described).
