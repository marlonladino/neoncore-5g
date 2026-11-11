# S-I3 owner decision options (security-reviewer, 2026-11-11, stage/L0 at 0f24789)

Saved by the lead from the security reviewer's returned text (condensed; nothing re-probed). Not yet decided by the owner.

## What S-I3 is
The approval flow decides "this is the owner" from an interactive terminal plus the absence of Claude Code environment markers (`scripts/approve.sh:14-19`, `infra/lib/approval_check.sh:15`, `plan_guard.py:133`). Any process running as the same OS user can fake both. A forged approval could unlock product writes, lab changes (terraform/ansible/VM power via `lab.sh`) and the confirmation before a VM is replaced, under a plan the owner never approved. The final build review re-tested 18 forms; 15 still got past the gate's text rules.

## Options
- **A. Accept as a documented risk (L0 only).** No code. Doc line in `docs/agent-gate.md`, accepted-risk entry in close.md, and the owner checks at each stage start that every approval file matches an approval they ran themselves. About 15 min plus about 1 min per stage. Stops nothing technically; the check can only catch a forgery after the fact. Fits a single-owner lab with nothing of value on it and a finished stage. Stops fitting at Stage 7, where logs, pcaps and SBI data enter agent context.
- **B. Harden the existing checks.** More gate.py patterns and tests. A few hours per round and it has not converged (three rounds of re-checks still found passing forms). Stops obvious and accidental forms only. gate.py matches command text inside the same trust boundary (`docs/agent-gate.md:59-66`). Only a stopgap alongside A or C.
- **C. Move approval outside the agents' reach.** `approve.sh` signs "stage kind sha256" (ssh-keygen -Y) with a key agents cannot use unattended (FIDO touch or passphrase key not in the agent's ssh-agent); gate.py and approval_check.sh verify against a committed allowed_signers file; TTY exemption removed; agents run as a separate OS user that cannot write gate/approval/allowed_signers files or read `.env.lab` (also the real fix for F-R2b). Estimate half a day to a day (not estimated in detail), needs a W0 amendment and owner approval. Not verified: passwordless sudo on the owner's user, FIDO key availability, Claude Code running cleanly as a second user.

## Reviewer recommendation
- L0 close: Option A, with an end date and a named follow-up. Owner should first confirm the L0 plan approvals (2026-11-09T23:23:52Z and 2026-11-10T00:02:24Z) were their own runs; this was not checked.
- Before Stage 7: Option C as a W0 amendment, built and tested before the Stage 7 plan is approved, keeping B's rules as a tripwire. Stage 7 must not be approved while S-I3 is open.
- F-R2b is a separate close-blocking item; it needs its own accepted-risk entry or a patch.

## Text for `docs/agent-gate.md:72-73` (owner or an agent whose scope covers it applies; scope not verified)
```
- Approvals are meant to be written only by a human at a TTY, the hash ties them to exact plan
  bytes, and `settings.json` denies edits to the gate itself. Changing the gate takes the owner's hand.
- **Known weakness (S-I3, accepted risk at L0 close):** the TTY and Claude Code marker checks can be faked by any process running as the same user, so an approval file is not proof the owner approved. Approvals are not signed yet. Fix: signed approvals plus a separate OS user for agents (W0 amendment), due before the Stage 7 plan is approved.
```

## Accepted-risk entry for close.md (wording is the reviewer's; no template exists)
```
Accepted risk S-I3 (approval forgery / TTY spoofing). Accepted by: the owner, on <date> at L0 close.
What is accepted: approve.sh, approval_check.sh and plan_guard.py identify the owner only by an
interactive terminal and the absence of Claude Code markers; an agent running as the same OS user
can fake both, and the gate's text rules do not fully block this (security review, final build
review: 15 of 18 re-tested forms pass). Approval files are not signed, so they are not proof of
owner approval. Mitigation until fixed: the owner checks, at each stage start, that every
approval file matches an approval they ran themselves.
Valid until: the W0 amendment below is built and tested, and in no case past approval of the
Stage 7 plan. Stage 7 must not be approved while S-I3 is open.
Follow-up: W0 amendment plan "signed approvals and separate agent OS user" (proposal
project/notes/L0-gate-proposal.md §6 and §6b(c)): ssh-keygen -Y signatures with a key agents
cannot use unattended, verified by gate.py and approval_check.sh; TTY exemption removed; agents
run as a user that cannot write gate, approval or allowed_signers files or read .env.lab.
Owner: the owner. Reviewer re-check: security-reviewer at that plan's close.
```
