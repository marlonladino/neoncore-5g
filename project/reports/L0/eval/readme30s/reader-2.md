# E9(b) reader 2: model reader

- Reader kind: model (fresh-context Claude Code -p session, no tools, no repo access). Not a human.
- Model ID (from session init): `claude-sonnet-5-5` (alias requested: `sonnet`)
- Session tools: []; MCP servers: []; exit code 0
- Isolation: empty working directory outside the repo, `--safe-mode`, `--setting-sources ''`, `--strict-mcp-config`, `--tools ''`, custom neutral system prompt, `--no-session-persistence`.
- Material (turn 1): README top section text (title to first `## `) with the GIF replaced by its alt text, plus GIF frame 250 of 1123 (PNG). Exact turn text: `turn-text.txt`.
- 'Page closed' (turn 2): the questions were sent only after the turn-1 reply arrived. A model keeps turn 1 in its context, so this is a comprehension check of the shown material, not a test of memory or of the 30 s time limit.
- Turn 1 reply (verbatim): `done`
- Latency: turn 1 4.98 s, turn 2 6.48 s. Session cost reported by the CLI: $0.0163313

## Answers (verbatim)

```text
**Q1. What is this?**
NeonCore 5G is a 5G standalone (SA) testbed. It uses Open5GS for the core and UERANSIM for the gNB and UE. It was built with AI agents under the owner's direction.

**Q2. What is it for, or where is it going?**
It's a lab for running and observing a 5G network. The stated direction is labeled faults and AI that finds them.

**Q3. What does it run on?**
It runs on single-node K3s inside a Proxmox VM. Monitoring uses Prometheus and Grafana, and there is packet tracing.

**Q4. How would you bring it up?**
Run `scripts/labenv infra/lab.sh up`.

**Q5. What can you see or do with it?**
The GIF shows a terminal "Control Center" with pod status for the core and monitoring namespaces. An action log shows results, such as a UE ping test through the uesimtun0 interface to 8.8.8.8. Key commands cover deploy, teardown, ping test, latest traces, run scenario, start/stop capture, and refresh. The status bar showed 16/17 pods running.

**Q6. What's done and what's planned?**
Done: the core and RAN testbed, the monitoring stack, packet tracing, and the terminal control center. Planned ("next"): labeled faults and AI that finds them. I don't know of any dates or further details.
```

## Scoring (evaluator, against the fixed key in plan section 8.5)

| Q | Key | Strict | Lenient | Note |
|---|---|---|---|---|
| Q1 | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or 'simulated gNB/UE') | 1 | 1 | 5G SA testbed; Open5GS core + UERANSIM gNB/UE named in the answer |
| Q2 | Generating labeled faults and/or an AI troubleshooter that finds them | 1 | 1 | labeled faults and AI that finds them |
| Q3 | A Proxmox VM, or single-node K3s/Kubernetes | 1 | 1 | single-node K3s inside a Proxmox VM |
| Q4 | One command (`lab.sh up`, or 'a single script') | 1 | 1 | `scripts/labenv infra/lab.sh up` |
| Q5 | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios | 1 | 1 | terminal Control Center (TUI), run scenario, start/stop capture |
| Q6 | That a roadmap or stages exist, with the lab done and the AI stages planned | 0 | 1 | done/planned split correct, but no roadmap or stages named |

**Strict (official): 5/6, Q1 correct -> PASS.** Lenient (sensitivity only): 6/6 -> PASS.
