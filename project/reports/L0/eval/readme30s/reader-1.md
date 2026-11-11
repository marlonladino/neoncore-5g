# E9(b) reader 1: model reader

- Reader kind: model (fresh-context Claude Code -p session, no tools, no repo access). Not a human.
- Model ID (from session init): `claude-opus-5-5` (alias requested: `opus`)
- Session tools: []; MCP servers: []; exit code 0
- Isolation: empty working directory outside the repo, `--safe-mode`, `--setting-sources ''`, `--strict-mcp-config`, `--tools ''`, custom neutral system prompt, `--no-session-persistence`.
- Material (turn 1): README top section text (title to first `## `) with the GIF replaced by its alt text, plus GIF frame 250 of 1123 (PNG). Exact turn text: `turn-text.txt`.
- 'Page closed' (turn 2): the questions were sent only after the turn-1 reply arrived. A model keeps turn 1 in its context, so this is a comprehension check of the shown material, not a test of memory or of the 30 s time limit.
- Turn 1 reply (verbatim): `done`
- Latency: turn 1 5.174 s, turn 2 5.534 s. Session cost reported by the CLI: $0.0302906

## Answers (verbatim)

```text
Q1. NeonCore 5G is a 5G standalone (SA) testbed. It pairs an Open5GS core with a UERANSIM gNB/UE, and it was built with AI agents under the owner's direction.

Q2. It's a lab for running and observing a 5G network. The plan is to add labeled faults and AI that detects and finds them.

Q3. It runs on single-node K3s inside a Proxmox VM.

Q4. Run `scripts/labenv infra/lab.sh up`.

Q5. A terminal control center shows pod status for the neoncore and monitoring namespaces, with Prometheus and Grafana for metrics. You can deploy or tear down, run a UE ping test (e.g., to 8.8.8.8 via uesimtun0), view latest traces, run scenarios, and start or stop packet capture.

Q6. Done: the core, gNB/UE, K3s setup, monitoring, packet tracing, and the control-center UI. Planned: labeled fault injection and AI-based fault finding.
```

## Scoring (evaluator, against the fixed key in plan section 8.5)

| Q | Key | Strict | Lenient | Note |
|---|---|---|---|---|
| Q1 | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or 'simulated gNB/UE') | 1 | 1 | 5G SA testbed; Open5GS core + UERANSIM gNB/UE named in the answer |
| Q2 | Generating labeled faults and/or an AI troubleshooter that finds them | 1 | 1 | labeled faults and AI that detects and finds them |
| Q3 | A Proxmox VM, or single-node K3s/Kubernetes | 1 | 1 | single-node K3s inside a Proxmox VM |
| Q4 | One command (`lab.sh up`, or 'a single script') | 1 | 1 | `scripts/labenv infra/lab.sh up` |
| Q5 | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios | 1 | 1 | terminal control center (TUI), Grafana, run scenarios, packet capture |
| Q6 | That a roadmap or stages exist, with the lab done and the AI stages planned | 0 | 1 | done/planned split correct (lab done, AI planned), but no roadmap or stages named |

**Strict (official): 5/6, Q1 correct -> PASS.** Lenient (sensitivity only): 6/6 -> PASS.
