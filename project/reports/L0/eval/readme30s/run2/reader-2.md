# E9(b) attempt 2, reader 2: model reader

- **Attempt 2, after a README change (`a59970b`), not an independent first run.** Attempt 1 is in `readme30s/` (FAIL strict). Scoring readings fixed before this run in `preregistration.md` (`fb1bab2`).
- Reader kind: model (fresh-context Claude Code -p session, no tools, no repo access). Not a human. New session; no memory of attempt 1.
- Model ID (from session init): `claude-sonnet-5-5` (alias requested: `sonnet`)
- Session tools: []; MCP servers: []; exit code 0
- Isolation: new empty working directory outside the repo, `--safe-mode`, `--setting-sources ''`, `--strict-mcp-config`, `--tools ''`, custom neutral system prompt, `--no-session-persistence`.
- Material (turn 1): README top section text at `a59970b` (title to first `## `) with the GIF replaced by its alt text, plus GIF frame 250 of 1123 (PNG, same bytes as attempt 1). Exact turn text: `turn-text.txt`.
- 'Page closed' (turn 2): the questions were sent only after the turn-1 reply arrived. A model keeps turn 1 in its context, so this is a comprehension check of the shown material, not a test of memory or of the 30 s time limit.
- Turn 1 reply (verbatim): `done`
- Latency: turn 1 4.114 s, turn 2 6.521 s. Session cost reported by the CLI: $0.017259

## Answers (verbatim)

```text
**Q1. What is this?**
NeonCore 5G is a 5G standalone (SA) testbed that combines the Open5GS core with a UERANSIM gNB and UE. It was built with AI agents under the owner's direction.

**Q2. What is it for, or where is it going?**
It is a lab for experimenting with 5G networks. The planned next step is labeled faults, plus AI that finds them.

**Q3. What does it run on?**
It runs on single-node K3s inside a Proxmox VM. Prometheus, Grafana and packet tracing are included.

**Q4. How would you bring it up?**
Run `scripts/labenv infra/lab.sh up`. I'm going from the command shown on the page and haven't seen anything beyond it.

**Q5. What can you see or do with it?**
The GIF shows a terminal control center that lists pod status in the monitoring and neoncore namespaces (16 of 17 running). Keys trigger deploy, teardown, a UE ping test, latest traces, running a scenario, start/stop capture and refresh. The ping test ran from the UE pod over uesimtun0 to 8.8.8.8 and succeeded. Grafana and Prometheus are also available for monitoring.

**Q6. What's done and what's planned?**
The testbed itself appears to be working: core, RAN simulator, monitoring, tracing and the control center. Labeled faults and AI fault-finding are planned. The README says the work follows a staged roadmap (W0 to 12) with per-stage status in a roadmap PDF. I don't remember which stages are finished.
```

## Scoring (evaluator, against the fixed key in plan section 8.5, readings pre-registered)

| Q | Key | Strict | Lenient | Note |
|---|---|---|---|---|
| Q1 | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or 'simulated gNB/UE') | 1 | 1 | 5G SA testbed; Open5GS core + UERANSIM gNB/UE named in the answer |
| Q2 | Generating labeled faults and/or an AI troubleshooter that finds them | 1 | 1 | labeled faults plus AI that finds them |
| Q3 | A Proxmox VM, or single-node K3s/Kubernetes | 1 | 1 | single-node K3s inside a Proxmox VM |
| Q4 | One command (`lab.sh up`, or 'a single script') | 1 | 1 | `scripts/labenv infra/lab.sh up` |
| Q5 | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios | 1 | 1 | terminal control center (TUI), running a scenario, start/stop capture, Grafana |
| Q6 | That a roadmap or stages exist, with the lab done and the AI stages planned | 1 | 1 | testbed working, labeled faults + AI planned, staged roadmap (W0 to 12) named; all three strict elements in this answer |

**Strict (official): 6/6, Q1 correct -> PASS.** Lenient (sensitivity only): 6/6 -> PASS.
