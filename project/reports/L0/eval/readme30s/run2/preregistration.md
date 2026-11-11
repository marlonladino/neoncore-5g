# E9(b) reader test, attempt 2: pre-registration

Written and committed by the evaluator BEFORE any attempt-2 reader ran.

**This is a second attempt after a README change, not an independent first run.** Attempt 1
(`8b9cab9`, files in `readme30s/` one level up, kept unchanged) FAILED the strict reading:
haiku 4/6 with Q1 incorrect; all three readers scored 0 on Q6 (no roadmap or stages named).
The README was then changed in `a59970b` (one sentence naming the staged roadmap, aimed at
Q6). That change was made with knowledge of the attempt-1 answers, so the Q6 result of this
attempt is not an independent measure of the README: the material was tuned against the same
questions and the same answer key. Q1 material (the first README sentence) is unchanged.

## Fixed for attempt 2 (same as attempt 1)

- Answer key: plan L0 section 8.5, unchanged. Questions Q1-Q6: unchanged, same wording.
- Readers: 3 model readers, aliases `opus`, `sonnet`, `haiku`, in that order; all three count
  toward the threshold. Each is a new `claude -p` session (no session persistence, so no
  memory of attempt 1), no tools, no MCP servers, no setting sources, `--safe-mode`, neutral
  system prompt, new empty working directory outside the repo. One run per reader.
- Material: README top section at `a59970b` (title down to the first `## `), image line
  replaced by the alt text, plus GIF frame 250 of 1123, the same PNG bytes as attempt 1
  (sha256 `43db9481f266697f41198aea13121a3f5991a93ced5ef82ddb471aed19f9c44a`; GIF sha256
  unchanged `917b47a4...bb00`).
- Method scripts: the attempt-1 scratch scripts, byte-identical (`build_input.py` sha256
  `91df8a56...86a`, `drive.py` sha256 `e5ed78b7...dd`). The only difference in the turn text
  against attempt 1 is the added README sentence (checked with `diff`).
- Threshold: each reader >= 5/6 with Q1 correct; >= 2 readers (plan E9). With 3 readers
  pre-registered, the verdict below needs all 3 to pass, as in attempt 1.

## Scoring rule, decided now (before answers are seen)

Attempt 1 chose its strict/lenient reading after seeing answers (disclosed there). For this
attempt both readings are fixed here, in advance, and they are the same readings attempt 1
used, so the two attempts are comparable.

- **STRICT (official verdict).** Each answer is scored on its own text only (an element that
  appears only in another answer does not count). Every element the key names must be present:
  - Q1: says 5G standalone (or 5G SA / 5G core) testbed or lab AND names at least one of
    Open5GS, UERANSIM, or a simulated gNB/UE.
  - Q2: labeled faults and/or an AI troubleshooter that finds faults.
  - Q3: Proxmox VM, or single-node K3s/Kubernetes.
  - Q4: one command (`lab.sh up` or "a single script").
  - Q5: any two of TUI/terminal control center, Grafana dashboards, packet captures/pcaps,
    scenarios.
  - Q6: names a roadmap or stages AND says the lab is done (or built/working) AND says the AI
    (or fault) part is planned. Missing any of the three -> 0.
- **LENIENT (sensitivity only, not the verdict).** The whole answer sheet counts for each
  question; Q6 also accepts a correct done/planned split without a roadmap or stages.
- A reader passes if its strict total >= 5 and its strict Q1 = 1. E9(b) PASS needs all 3
  readers to pass strictly. Any other outcome is FAIL and is reported as such.

## Cost estimate (before the run)

Attempt 1 cost $0.0474 for the same 3 sessions (CLI-reported). Estimate for attempt 2:
< $0.10. This is Claude Code session usage, outside `project/budget.yaml` per plan section 10
(as in attempt 1); even if counted, it is far below the $25 monthly API cap with an empty
ledger. Abort rule: stop if a single session reports > $0.10.
