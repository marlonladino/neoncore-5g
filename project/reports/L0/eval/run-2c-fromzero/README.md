# L0 run R2c (T9), Proxmox lab after from-zero attempt 2

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8 (approved hash 1310dd1c...), R2 = E5, then E1, E2, E3 (5 suites), E4, E6, E7, C1-C4. This is the full R2 rerun after R2b (`../run-2b-fromzero/`) failed E1 on sampling coverage, on the same VM built by from-zero attempt 2 (`../fromzero-2/`). No lab change since the from-zero run at `b9377fc`: `b9377fc..4387a7f` changes only files under `project/notes/` and `project/reports/` (checked with `git diff --stat`, 0 files outside `project/`).
Run window (pods-start to pods-end): 2026-11-10T21:26:59Z (epoch 1794346019.35) to 21:52:00Z (epoch 1794347520.81), 1501.5 s.

**R2c verdict: PASS.** E1, E2 (3/3), E3 (15/15), E4, E6(a), E7 (allowlisted scan 2 of 2, non-allowlisted scan 1 of 2, guard, NAD) pass. E6(b) is met (kubeconfig match, R2 passes). C1-C4 are "not tested: no baseline" (owner waiver). With R2c passing, E5 is PASS for from-zero attempt 2 (see the E5 row).

## Procedure fix (no threshold change, no script change)
R2b took pods-end 125 s after the soak returned. In R2c, pods-start, the soak and pods-end ran as one chained background invocation (`pods_check.py snapshot` ; `pods_check.py soak --duration-s 1500 --interval-s 60` ; `pods_check.py snapshot`), so pods-end was taken as soon as the soak returned (soak returned 21:52:00Z, pods-end exit 21:52:01Z). No file under `evals/` changed; the run used the committed scripts at `4387a7f`.
- Pre-check (before the run): a 1500 s soak at 60 s takes samples at offsets 0 to 1440 s, so 25 samples; with pods-end at once, the window is about 1500 s plus the two snapshot times, and the rule needs floor(window / 60) - 1 = 24 (it would need 26 only for a window of 1620 s or more). 25 >= 24.
- Measured: 25 samples, window 1501.5 s, needed 24. Gaps: pods-start to first sample 0.8 s, between samples max 60.0 s, last sample (21:51:00Z) to pods-end 60.6 s. The lead asked for a gap under 60 s; the last gap is 60.6 s, because the soak sleeps one full interval after its last sample before it returns. That gap is not a threshold; the binding rule (sampling coverage) holds with 1 sample of margin.

## Provenance
- Git SHA at run start: `4387a7f` (clean tree, 0 porcelain lines at 21:26:50Z). No commit by the evaluator during the run; scripts record the SHA they saw (their porcelain count includes this run's own untracked folder).
- Tools: tshark 4.2.2, nmap 7.94SVN (control machine), nmap 7.993 (owner's laptop, as reported in its XML), kubectl client v1.37.2, server v1.36.6+k3s1, Python 3.12.3. Images and NF versions: `versions.txt`. Pcap sha256: `SHA256SUMS` (pcaps stay local, uncommitted, git-ignored).
- Cost estimate: $0 (no API, GPU or cloud calls; budget.yaml caps 25 / 0 / 0 USD per month). Actual: $0.
- Baseline B: none (owner waiver, WSL2 VM deleted). C1-C4 "not tested: no baseline"; [B] items reported, not required; reject cause must be 7.
- Redaction: JSON evidence from pods_check, ping_check, pcap_check, prom_check, scan_parse, compare_baseline, mtu_check, capture_baseline and wsl_grep was written with site values loaded (scripts run under the lab env wrapper). The suite logs, `lan/nad.json` and this README went through redact.py without site values (redact.py is not on the gate's allowlist under the wrapper); structural, address and hostname redaction still applied. A no-site-values re-scan of every committed file in this folder: 0 hits.
- Tracer: deployment has `shareProcessNamespace: true` (checked live at 21:26Z). Tracer freshness: "fresh" before pods-start, inside each E2 run, and after E3 suite 5 (21:40:20Z).

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| E7 non-allowlisted scan 1 (owner, LAN laptop, Windows, admin; TCP, then UDP, then SCTP), lab idle | 2026-11-10T20:52:15Z (XML; owner console 20:52:08Z) | 21:19:27Z (XML; owner console 21:19:30Z); TCP 1490.19 s, UDP 3.05 s, SCTP 2.82 s |
| pods-start | 1794346019 (21:26:59Z) | |
| soak (1500 s, 60 s interval, background, chained with pods-start and pods-end) | 1794346020 (first sample) | 1794347520 (last sample 1794347460, 21:51:00Z) |
| E7 allowlisted scan (`nmap -Pn -sS -p-`, sudo, control machine) | 1794346034 | 1794346138 |
| E2 runs 1-3 (+ informational 1372-byte DF ping each) | 1794346138 | 1794346377 |
| laptop scan parse, scan target checks | after E2 | before E3 |
| E3 suites 1-5 (back to back, check + copy after each) | 1794346558 | 1794346819 |
| E6(a) static grep, E6(b) kubeconfig compare, nft check, NAD (live 21:41:10Z), MTU, versions, workloads | after E3 | before pods-end |
| pods-end (same invocation as the soak) | 1794347520 (21:52:00Z) | |
| E4 (Grafana NodePort, Prometheus NodePort), window = pods-start to pods-end | after pods-end | |

Neither scan overlapped E2 or E3. The 3 laptop scan XMLs and the allowlisted scan XML target the kubeconfig server host (checked in memory, "match" only). All 15 E3 pcaps show 0 frames from non-pod sources.

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E5 | **PASS** (attempt 2) | preconditions met; run 3 exit 0 (396 s), owner attests "rebuilt, and nothing was added manually", log shows no gap or manual command; idempotency PASS; R2 passes in full (this run, R2c), on the same VM with no lab change since the from-zero commit | `../fromzero-2/`, this README |
| E1 | PASS | 25 soak samples (needed 24, window 1501.5 s, >= 900 s); all workload pods Running with all containers Ready at start, 25 samples and end; no pod Pending/Failed/Unknown/CrashLoopBackOff; dbctl Job succeeded=1, pod Succeeded; 0 leftover scenario-ue pods at the end; same 17 pods at start and end; restart delta 0 for every container (total restart count 0 at start and at end, incl. `neoncore/tracer`); 0 soak samples failed to read the cluster. C1 not tested: no baseline; C4 absolute part PASS | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json` |
| E2 | PASS (3/3) | 20/20, 20/20, 20/20 replies; N3 in +20/+20/+20, out +20/+20/+20; RTT p50/p95 ms 5.06/6.79, 5.14/6.05, 5.26/11.4. [B] GTP-U: tested, tracer fresh in all 3 runs; `gtp && icmp` frames 80, 80, 20 (not de-duplicated; see observations for run 3). Informational 1372-byte DF ping: 3/3 received in all 3 runs | `ping-1..3.txt`, `ping-pmtu-1..3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 | PASS | 15/15 scenario executions PASS with valid pcaps (V0-V2), 0 retries; Wilson 95% CI [0.796, 1.000]; reject cause 7 in 5/5, no accept for the reject UE; deregistration switch_off 0 and 0x46 in 5/5; no PDU session reject; every [B] item present in 15/15 (PFCP tied in all 10 initial-registration and deregistration pcaps). Suite wall times 43, 42, 41, 41, 42 s. C2 not tested: no baseline | `suite-1..5.log`, `pcap-summary-1..5.json`, `pcap-summary.json`, `SHA256SUMS`, `pcaps/` (local); report-only `pcap-observations.json` |
| E4 | PASS | 10 panels / 18 targets; 17 with data; `pdusessioncreationfail` absent (allowed); reginitreq 22 -> 42 (+20, >= 15); reginitsucc 16 -> 31 (+15, >= 10); N3 in/out rate max in the E2 windows 0.16/0.16, 0.36/0.36, 0.36/0.36 per s; Panel 1 = 1 for every workload pod at the end (dbctl excluded); 6/6 Prometheus targets up; C3 not tested: no baseline | `grafana-panels.json`, `prom-targets.json`, `e4.json`, `compare.json` |
| E6(a) | PASS | 0 FAIL hits, 571 allowed hits, 0 other, at `4387a7f` (allowed hits rose from 282 in R2b because R2b's committed evidence under `project/**` quotes the pattern words; allowed by the plan) | `wsl/grep.txt`, `wsl/allowlist-hits.txt`, `wsl/static.json` |
| E6(b) | PASS | kubeconfig server host vs the Terraform state VM IPv4 (1 static address in `initialization`; Terraform outputs only `vm_id`): match, compared in memory at 21:40Z; old host VM deleted, so R2c ran without it; R2 passes (this run) | this README |
| E6(c) | not tested | R4 / T15a not run | |
| E7 allowlisted (2 of 2: R1, R2) | PASS | open TCP {22, 6443, 30030, 30090} = D7(a); 65531 filtered | `lan/scan-allow-2.txt`, `.json` |
| E7 non-allowlisted scan 1 (1 of 2; scan 2 is R3 after a reboot) | PASS | TCP 0 open of 65535 (65535 filtered, no-response); UDP 0 open, 8/8 open\|filtered; SCTP 0 open (2/2 filtered) | `lan/scan-nonallow-1.txt`, `.json` |
| E7 guard + NAD | PASS | guard: lab-ops' capture on this VM (2026-11-10T20:12:05Z, `bc3d615`; same VM, no lab change since), copied from `../run-2b-fromzero/lan/nft-ruleset.txt` and re-checked by `scan_parse.py nft`: `inet neoncore_guard` present, prerouting at -150, ct invalid drop, established/related accept, allow rule for the D7(a) ports, final counter drop. NAD: evaluator live check 21:41:10Z, resource type absent, 0 NADs, 4 K3s CRDs only, 0 API resources matching; no pod requests a secondary network (14 + 3 pods, network-status only `cbr0` on `eth0`) | `lan/nft-ruleset.txt`, `lan/nft-check.json`, `lan/nad.json` |
| TB6 MTU (informational) | recorded | pods (evaluator, 21:41:30Z): gnb/upf/ue eth0 1450, upf ogstun 1500, ue uesimtun0 1400. Node, measured by lab-ops on this VM at 20:45:48Z (`4387a7f`, notes "Node MTU, from-zero attempt 2 VM"): VM NIC 1500, flannel.1 1450, cni0 1450. Proxmox bridge 1500, no VLAN (owner-supplied, not measured). 1372-byte DF ping 3/3 x 3 runs, plus 3/3 in `versions.txt` | `mtu.txt`, `ping-n3.json`, `versions.txt` |
| C1-C4 | not tested: no baseline | C4 absolute part only: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `compare.json`, `versions.txt` |

## Observations (report-only, no threshold)
- **E2 run 3 GTP-U count.** The tracer rotated its capture file at 21:32:25Z, inside the run 3 ping window (21:32:09Z to 21:32:28Z). ping_check counts only the tracer's newest file, so run 3 shows 20 `gtp && icmp` frames (10 request, 10 reply) instead of about 80. The [B] item needs > 0, and the N3 counters (+20/+20) cover the whole window. Report-only.
- **Tracer.** 0 restarts over the 1501.5 s window, through 3 E2 runs and 5 E3 suites; freshness "fresh" before the run, in each E2 run and after suite 5.
- Run UE GUTI re-registration after deregistration: 5 of 5 deregistration pcaps (R2b: 5 of 5). Every non-run NGAP id in these pcaps is that GUTI re-registration (its 5G-TMSI equals the one assigned to the run UE), so the background `ue` pod sent no N2 signalling in any pcap. No 5GMM STATUS in any pcap. Auth failure #21 before every SUCI registration: 10/10 (as in R1, R2 and R2b, O-3). NEA0 in all 10 SMCs (the 5 reject pcaps have no SMC).
- One registration-reject pcap (`...-213808`) holds PFCP frames; pcap_check reports its PFCP tie as "untied" (the other 4: "no-pfcp"). Report-only; the reject scenario has no PFCP requirement.
- `capture_baseline.sh versions` printed "mtu_check: bad --label" again (its internal label has parentheses). Known since R2 attempt 1, not fixed (no `evals/` change during a run); the pod MTUs are in `mtu.txt` from a direct run, so nothing is missing.
- Raw scan XML (not committed; sha256 prefix for provenance): laptop TCP `4977ce86...`, UDP `00ef5feb...`, SCTP `0fa1ade0...` (in the owner's scan folder outside the repo); control-machine allowlisted `9671ba9e...` (session scratchpad, deleted with the session).

## Not tested in R2c
- C1-C4 (no baseline). E6(c) (R4 / T15a). E7 non-allowlisted scan 2 (R3, after a reboot). Proxmox bridge MTU (owner-supplied, not measured). Scenario durations per scenario (the suite logs carry no per-line timestamps; suite wall times only). E8, E9 and E10 are not part of R2 (E10 was R1).
