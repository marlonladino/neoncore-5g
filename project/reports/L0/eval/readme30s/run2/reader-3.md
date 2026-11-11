# E9(b) attempt 2, reader 3: model reader

- **Attempt 2, after a README change (`a59970b`), not an independent first run.** Attempt 1 is in `readme30s/` (FAIL strict). Scoring readings fixed before this run in `preregistration.md` (`fb1bab2`).
- Reader kind: model (fresh-context Claude Code -p session, no tools, no repo access). Not a human. New session; no memory of attempt 1.
- Model ID (from session init): `claude-haiku-5-5` (alias requested: `haiku`)
- Session tools: []; MCP servers: []; exit code 0
- Isolation: new empty working directory outside the repo, `--safe-mode`, `--setting-sources ''`, `--strict-mcp-config`, `--tools ''`, custom neutral system prompt, `--no-session-persistence`.
- Material (turn 1): README top section text at `a59970b` (title to first `## `) with the GIF replaced by its alt text, plus GIF frame 250 of 1123 (PNG, same bytes as attempt 1). Exact turn text: `turn-text.txt`.
- 'Page closed' (turn 2): the questions were sent only after the turn-1 reply arrived. A model keeps turn 1 in its context, so this is a comprehension check of the shown material, not a test of memory or of the 30 s time limit.
- Turn 1 reply (verbatim): `done`
- Latency: turn 1 3.141 s, turn 2 4.306 s. Session cost reported by the CLI: $0.0008139

## Answers (verbatim)

```text
Q1. NeonCore 5G is a 5G standalone (SA) testbed project, with a terminal control center shown in its demo GIF.

Q2. It's a lab for running and studying a 5G core and radio, with the next step being labeled faults and AI that finds them.

Q3. It runs Open5GS core and UERANSIM gNB/UE on single-node K3s, inside a Proxmox VM, with Prometheus, Grafana, and packet tracing.

Q4. The README gives the command `scripts/labenv infra/lab.sh up`. I don't remember the prerequisites beyond what the page shows, so I can't say more.

Q5. From the demo frame, you can see pod status across the core and monitoring namespaces, run a UE ping test, view latest traces, run scenarios, start or stop capture, and refresh. The frame shows 16 of 17 pods Running and a successful ping from the UE pod to 8.8.8.8.

Q6. I don't know which stages are done. The page only says the work follows a staged roadmap (W0 to 12) and points to a roadmap PDF for per-stage status. Labeled faults and AI fault-finding are described as planned.
```

## Scoring (evaluator, against the fixed key in plan section 8.5, readings pre-registered)

| Q | Key | Strict | Lenient | Note |
|---|---|---|---|---|
| Q1 | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or 'simulated gNB/UE') | 0 | 1 | says '5G standalone (SA) testbed project, with a terminal control center' but names none of Open5GS, UERANSIM, simulated gNB/UE in this answer (they appear only in its Q3 answer); strict per-answer rule -> incorrect (same failure as attempt 1) |
| Q2 | Generating labeled faults and/or an AI troubleshooter that finds them | 1 | 1 | labeled faults and AI that finds them |
| Q3 | A Proxmox VM, or single-node K3s/Kubernetes | 1 | 1 | Open5GS/UERANSIM on single-node K3s inside a Proxmox VM |
| Q4 | One command (`lab.sh up`, or 'a single script') | 1 | 1 | `scripts/labenv infra/lab.sh up` |
| Q5 | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios | 1 | 1 | run scenarios, start or stop capture (two of the key items; same reading as attempt 1) |
| Q6 | That a roadmap or stages exist, with the lab done and the AI stages planned | 0 | 1 | names the staged roadmap (W0 to 12) and says labeled faults + AI are planned, but says 'I don't know which stages are done' and does not say the lab is done or working -> strict 0. Lenient 1 (judgment call): its Q3/Q5 answers describe a running lab ('16 of 17 pods Running', successful UE ping) |

**Strict (official): 4/6, Q1 INCORRECT -> FAIL.** Lenient (sensitivity only): 6/6 -> PASS.
