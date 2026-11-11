# L0 run R2 (T9), Proxmox lab after the from-zero rebuild

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8 (approved hash 1310dd1c...), R2 = E5, then E1, E2, E3 (5 suites), E4, E6, E7, C1-C4.
Run window (pods-start to pods-end): 2026-11-10T17:36:49Z (epoch 1794332209) to 18:02:08Z (epoch 1794333728), 1519 s.

**R2 verdict: FAIL.** E1 failed (tracer container restarted once during the soak) and E6(a) failed (2 hits in executable/config files). Per section 8 §2 a failed threshold fails the run; the fix must be followed by a full R2 rerun. Partial reruns don't count.

## Provenance
- Git SHA at run start: 6e56129 (clean tree except this run's own evidence). No commit by the evaluator during the run; scripts record the SHA they saw.
- Tools: tshark 4.2.2, nmap 7.94SVN (control machine), nmap 7.993 (owner's laptop, as reported in its XML), kubectl client v1.37.2, server v1.36.6+k3s1, Terraform v1.17.1, Python 3.12.3. Images and NF versions: `versions.txt`. Pcap sha256: `SHA256SUMS` (pcaps stay local, uncommitted).
- Cost estimate: $0 (no API, GPU or cloud calls; budget.yaml caps 25 / 0 / 0 USD per month). Actual: $0.
- Baseline B: none (owner waiver, WSL2 VM deleted). C1-C4 "not tested: no baseline"; [B] items reported, not required; reject cause must be 7.
- Redaction: JSON evidence from pods_check, ping_check, pcap_check, prom_check, scan_parse and compare_baseline was written with site values loaded. The suite logs, `lan/nft-ruleset.txt`, `lan/nad.json`, this README and `../wsl/runtime.txt` went through redact.py without site values (redact.py is not on the gate's allowlist under the lab env wrapper); structural, address and hostname redaction still applied. R1 suite logs held no site-value placeholders either.

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| E7 non-allowlisted scan 1 (owner, LAN laptop; TCP, then UDP, then SCTP) | 2026-11-10T16:53:56Z | about 17:22:04Z (TCP 1485.48 s, UDP 3.19 s, SCTP 3.05 s) |
| pods-start | 1794332209 | |
| soak (1500 s, 60 s interval) | 1794332218 | 1794333718 |
| E7 allowlisted scan (`nmap -Pn -sS -p-`, sudo, control machine) | 1794332257 | 1794332361 |
| E2 runs 1-3 (+ informational 1372-byte DF ping each) | 1794332417 | 1794332640 |
| E6(a) static grep (read-only, during E2) | about 1794332500 | |
| E3 suites 1-5 (back to back, check + copy after each) | 1794332664 | 1794332897 |
| pods-end | 1794333728 | |
| E4 (Grafana NodePort, Prometheus NodePort), window = pods-start to pods-end | after pods-end | |

Neither scan overlapped E2 or E3. The laptop scan ran before the R2 window, with the lab idle (lead's relay). All 15 E3 pcaps show 0 frames from non-pod sources. All 4 scan XMLs target the kubeconfig server host (checked in memory, "match" only).

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E5 | not PASS (R2 failed) | preconditions met; first invocation exit 0 (398 s), owner attests "Yes, no manual step", log shows no gap; idempotency PASS | `../fromzero/` |
| E1 | **FAIL** | soak 1518.9 s, 25 samples; restart delta 1 for `neoncore/tracer` (container killed by its liveness probe at 17:48:43Z, exit 137, running again 17:49:14Z); every other container delta 0; all workload pods Running/Ready at every sample; dbctl Succeeded; 0 leftover scenario-ue; C1/C4 not tested: no baseline | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json` |
| E2 | PASS (3/3) | 20/20, 20/20, 20/20 replies; N3 in +20/+20/+20, out +20/+20/+20; RTT p50/p95 ms 5.21/5.73, 5.18/10.2, 5.08/5.65. [B] GTP-U: tested, tracer fresh in all 3 runs; `gtp && icmp` frames 80, 76, 80 (not de-duplicated; run 2 straddled a tracer file rotation). Informational 1372-byte DF ping: 3/3 received in all 3 runs | `ping-1..3.txt`, `ping-pmtu-1..3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 | PASS | 15/15 scenario executions PASS with valid pcaps, 0 retries; Wilson 95% CI [0.796, 1.000]; reject cause 7 in 5/5; deregistration switch_off 0 and 0x46 in 5/5; every [B] item present in 15/15 (PFCP tied in all 10 initial-registration and deregistration pcaps) | `suite-1..5.log`, `pcap-summary-1..5.json`, `pcap-summary.json`, `SHA256SUMS`, `pcaps/` (local); report-only `pcap-observations.json` |
| E4 | PASS | 10 panels / 18 targets; 17 with data; `pdusessioncreationfail` absent (allowed); reginitreq 2 -> 21 (+19, >= 15); reginitsucc 2 -> 15 (+13, >= 10); N3 rate max in the E2 windows 0.16 / 0.32 / 0.40 per s; Panel 1 = 1 for every workload pod (dbctl excluded); 6/6 Prometheus targets up; C3 not tested: no baseline | `grafana-panels.json`, `prom-targets.json`, `e4.json`, `compare.json` |
| E6 | **FAIL** | (a) 2 FAIL hits: `infra/README.md:84` (E5 precondition 4 text) and `scripts/tests/test_gate.py:86` (the eval script file name in a list); 137 allowed hits; 0 other. (b) kubeconfig server host vs Terraform VM address: match; old host VM deleted; but "R2 passes" is part of (b), so (b) is not met. (c) not tested (R4 not run) | `../wsl/grep.txt`, `../wsl/allowlist-hits.txt`, `../wsl/static.json`, `../wsl/runtime.txt` |
| E7 allowlisted (2 of 2: R1, R2) | PASS | open TCP {22, 6443, 30030, 30090} = D7(a); 65531 filtered | `lan/scan-allow-1.txt`, `.json` |
| E7 non-allowlisted scan 1 (1 of 2; scan 2 is R3 after a reboot) | PASS | TCP 0 open of 65535 (65535 filtered); UDP 0 open, 8/8 open\|filtered; SCTP 0 open (2 filtered) | `lan/scan-nonallow-1.txt`, `.json` |
| E7 guard + NAD | PASS | `inet neoncore_guard` present, prerouting at mangle (-150), ct invalid drop, final counter drop, allow rule for 22/6443/30030/30090 (lab-ops capture 16:50:06Z, 087f7b0); NAD resource type absent, 0 NADs, no pod requests a secondary network (live, evaluator) | `lan/nft-ruleset.txt`, `lan/nft-check.json`, `lan/nad.json` |
| TB6 MTU (informational) | recorded | pods: gnb/upf/ue eth0 1450, upf ogstun 1500, ue uesimtun0 1400 (evaluator, 17:36:58Z); VM NIC 1500, flannel.1 1450, cni0 1450 (lab-ops, measured on the VM, `project/notes/L0.md`); Proxmox bridge 1500, no VLAN (owner-supplied, not measured); 1372-byte DF ping 3/3 x 3 | `mtu.txt`, `ping-n3.json` |
| C1-C4 | not tested: no baseline | C4 absolute part only: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `compare.json` |

## Observations
- **E1 failure cause (evidence, not a diagnosis).** Tracer files (pod clock): `neoncore-20261110-174158.pcap` was compressed at 17:44:29Z, about 2.5 min before its 5-minute rotation, and no new capture file appeared until `neoncore-20261110-174914.pcap` after the restart. The main capture therefore stopped at about 17:44:29Z, which is 5 s after E3 suite 1 started (17:44:24Z). The liveness probe (newest pcap older than 120 s, period 60 s, failureThreshold 3) then killed the container at 17:48:43Z, as designed. The previous container's log shows only tcpdump's start lines. Hypothesis to check (lab-ops/developer): the phase6 per-scenario capture or its cleanup ends the main tcpdump in the tracer pod, and the capture loop does not start a new one. E2 GTP-U was measured before this (17:40-17:43Z) on fresh files. E3 pcaps come from phase6's own captures and are valid.
- The tracer's own fix (compression in the loop) worked for rotations before 17:44Z (5-min cadence 17:11:57Z to 17:41:58Z) and again after the restart.
- Run UE GUTI re-registration after deregistration: 4 of 5 deregistration pcaps (R1: 3 of 5); one 5GMM STATUS #101. Auth failure #21 before every SUCI registration: 10/10 (as in R1, O-3). NEA0 in all 14 SMCs.
- One registration-reject pcap (`...-174439`) holds 4 PFCP frames; pcap_check reports its PFCP tie as "untied" (the other 4 reject pcaps: "no-pfcp"). Report-only; the reject scenario has no PFCP requirement.
- `capture_baseline.sh versions` printed "mtu_check: bad --label" (its internal MTU call); the pod MTU lines are in `mtu.txt` from a direct run, so nothing is missing. Evaluator bug, to fix before R3.
- Gate pattern detail: the allowlisted script form must be followed by whitespace or end of text; `<script>;` is blocked. The evaluator passed an explicit argument.

## Not tested in R2
- C1-C4 (no baseline). E6(c) (R4). E7 non-allowlisted scan 2 (R3, after a reboot). E8, E9 and E10 are not part of R2 (E10 was R1).
