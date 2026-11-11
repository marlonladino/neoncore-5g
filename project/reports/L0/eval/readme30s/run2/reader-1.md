# E9(b) attempt 2, reader 1: model reader

- **Attempt 2, after a README change (`a59970b`), not an independent first run.** Attempt 1 is in `readme30s/` (FAIL strict). Scoring readings fixed before this run in `preregistration.md` (`fb1bab2`).
- Reader kind: model (fresh-context Claude Code -p session, no tools, no repo access). Not a human. New session; no memory of attempt 1.
- Model ID (from session init): `claude-opus-5-5` (alias requested: `opus`)
- Session tools: []; MCP servers: []; exit code 0
- Isolation: new empty working directory outside the repo, `--safe-mode`, `--setting-sources ''`, `--strict-mcp-config`, `--tools ''`, custom neutral system prompt, `--no-session-persistence`.
- Material (turn 1): README top section text at `a59970b` (title to first `## `) with the GIF replaced by its alt text, plus GIF frame 250 of 1123 (PNG, same bytes as attempt 1). Exact turn text: `turn-text.txt`.
- 'Page closed' (turn 2): the questions were sent only after the turn-1 reply arrived. A model keeps turn 1 in its context, so this is a comprehension check of the shown material, not a test of memory or of the 30 s time limit.
- Turn 1 reply (verbatim): `done`
- Latency: turn 1 4.791 s, turn 2 6.528 s. Session cost reported by the CLI: $0.031925999999999996

## Answers (verbatim)

```text
**Q1.** NeonCore 5G is a 5G standalone (SA) testbed: an Open5GS core plus UERANSIM gNB/UE, with monitoring and packet tracing.

**Q2.** The next planned step is to inject labeled faults and use AI to find them. The work follows a staged roadmap (stages W0 to 12).

**Q3.** It runs on single-node K3s inside a Proxmox VM.

**Q4.** Run `scripts/labenv infra/lab.sh up`.

**Q5.** The terminal control center shows the status of the pods (core functions plus Prometheus, Grafana and kube-state-metrics). It has keys to deploy, tear down, run a UE ping test (for example, a ping to 8.8.8.8 through uesimtun0), view the latest traces, run scenarios, start or stop packet capture, and refresh. Grafana dashboards are also available.

**Q6.** The core, RAN simulation, monitoring and tracing are working; the demo showed 16 of 17 pods running. Labeled faults and AI-based detection are planned. I don't remember the status of each stage; that's in the linked roadmap PDF.
```

## Scoring (evaluator, against the fixed key in plan section 8.5, readings pre-registered)

| Q | Key | Strict | Lenient | Note |
|---|---|---|---|---|
| Q1 | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or 'simulated gNB/UE') | 1 | 1 | 5G SA testbed; Open5GS core + UERANSIM gNB/UE named in the answer |
| Q2 | Generating labeled faults and/or an AI troubleshooter that finds them | 1 | 1 | labeled faults and AI to find them |
| Q3 | A Proxmox VM, or single-node K3s/Kubernetes | 1 | 1 | single-node K3s inside a Proxmox VM |
| Q4 | One command (`lab.sh up`, or 'a single script') | 1 | 1 | `scripts/labenv infra/lab.sh up` |
| Q5 | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios | 1 | 1 | terminal control center (TUI), run scenarios, packet capture, Grafana dashboards |
| Q6 | That a roadmap or stages exist, with the lab done and the AI stages planned | 1 | 1 | lab working (core, RAN sim, monitoring, tracing), labeled faults + AI planned, names stages and the roadmap PDF; all three strict elements in this answer |

**Strict (official): 6/6, Q1 correct -> PASS.** Lenient (sensitivity only): 6/6 -> PASS.
