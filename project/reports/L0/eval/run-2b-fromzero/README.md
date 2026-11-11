# L0 run R2b (T9), Proxmox lab after from-zero attempt 2

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8 (approved hash 1310dd1c...), R2 = E5, then E1, E2, E3 (5 suites), E4, E6, E7, C1-C4. This is the full R2 rerun after R2 attempt 1 (`../run-2-fromzero/`) failed E1 and E6(a), on the VM built by from-zero attempt 2 (`../fromzero-2/`).
Run window (pods-start to pods-end): 2026-11-10T20:13:58Z (epoch 1794341638) to 20:41:08Z (epoch 1794343268), 1630.4 s.

**R2b verdict: FAIL.** E1 failed on its sampling-coverage rule: the last soak sample was at 20:38:03Z and the evaluator took pods-end at 20:41:08Z, so 185 s of the run window had no sample (25 soak samples, the script requires floor(1630.4 / 60) - 1 = 26). The cause is the evaluator's procedure (pods-end taken 125 s after the soak returned), not the lab: every health condition of E1 held at all 27 samples, and the restart delta was 0 for every container. E2, E3, E4, E6 and E7 passed. Per section 8 §2 a failed threshold fails the run; a full R2 rerun is needed. Partial reruns don't count, so E1 is not re-evaluated here. No fix, no lab change.

## Provenance
- Git SHA at run start: `bc3d615` (clean tree, 0 porcelain lines at 20:13:42Z). The from-zero run was at `b9377fc`; `b9377fc..bc3d615` changes only `project/notes/` (redacted lab-up logs, lab-ops' E7 capture), no code or config. No commit by the evaluator during the run; scripts record the SHA they saw (their porcelain count includes this run's own untracked folder).
- Tools: tshark 4.2.2, nmap 7.94SVN (control machine), nmap 7.993 (owner's laptop, as reported in its XML), kubectl client v1.37.2, server v1.36.6+k3s1, Python 3.12.3. Images and NF versions: `versions.txt`. Pcap sha256: `SHA256SUMS` (pcaps stay local, uncommitted, git-ignored).
- Cost estimate: $0 (no API, GPU or cloud calls; budget.yaml caps 25 / 0 / 0 USD per month). Actual: $0.
- Baseline B: none (owner waiver, WSL2 VM deleted). C1-C4 "not tested: no baseline"; [B] items reported, not required; reject cause must be 7.
- Redaction: JSON evidence from pods_check, ping_check, pcap_check, prom_check, scan_parse, compare_baseline, mtu_check, capture_baseline and wsl_grep was written with site values loaded (scripts run under the lab env wrapper). The suite logs, `lan/nft-ruleset.txt`, `lan/nad.json` and this README went through redact.py without site values (redact.py is not on the gate's allowlist under the wrapper); structural, address and hostname redaction still applied.
- Tracer: deployment has `shareProcessNamespace: true` (the E1 fix, `f2ec4b1`), checked live at 20:13Z. Tracer freshness: "fresh" before pods-start, inside each E2 run, and after E3 suite 5.

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| E7 non-allowlisted scan 1 (owner, LAN laptop, Windows, admin prompt; TCP, then UDP, then SCTP), lab idle | 2026-11-10T19:33:32Z (XML; owner console 19:33:24Z) | 20:03:12Z (XML; owner console 20:03:18Z); TCP 1484.18 s, UDP 3.17 s, SCTP 2.21 s |
| lab-ops E7 capture on the VM (nft ruleset, NAD, CRDs), read-only | 2026-11-10T20:12:05Z | |
| pods-start | 1794341638 (20:13:58Z) | |
| soak (1500 s, 60 s interval, background) | 1794341638 | 1794343143 (last sample 1794343083, 20:38:03Z) |
| E7 allowlisted scan (`nmap -Pn -sS -p-`, sudo, control machine) | 1794341651 | 1794341755 |
| E2 runs 1-3 (+ informational 1372-byte DF ping each) | 1794341770 | 1794341996 |
| E3 suites 1-5 (back to back, check + copy after each) | 1794342010 | 1794342277 |
| E6(a) static grep, E6(b) kubeconfig compare, laptop scan parse, nft/NAD, MTU, versions | after E3 | before pods-end |
| pods-end | 1794343268 (20:41:08Z) | |
| E4 (Grafana NodePort, Prometheus NodePort), window = pods-start to pods-end | after pods-end | |

Neither scan overlapped E2 or E3. The 3 laptop scan XMLs target the kubeconfig server host (checked in memory, "match" only); the allowlisted scan used that host by construction. All 15 E3 pcaps show 0 frames from non-pod sources.

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E5 | not PASS (R2b failed) | preconditions met; run 3 exit 0 (396 s), owner attests "rebuilt, and nothing was added manually", log shows no gap or manual command; idempotency PASS | `../fromzero-2/` |
| E1 | **FAIL** | failure: "25 soak samples < 26 expected at 60 s" (run window 1630.4 s; samples at 20:13:58Z start, 20:14:03Z to 20:38:03Z every 60 s, max gap 60.0 s, then 185 s to pods-end at 20:41:08Z). Every other E1 condition held: restart delta 0 for all 17 pods' containers incl. `neoncore/tracer` (the R2 attempt 1 failure mode did not recur across 5 suites); all workload pods Running/Ready at every sample; dbctl Job succeeded=1, pod Succeeded; 0 leftover scenario-ue; same 17 pods at start and end (no pod recreated). C1/C4 not tested: no baseline | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json` |
| E2 | PASS (3/3) | 20/20, 20/20, 20/20 replies; N3 in +20/+20/+20, out +20/+20/+20; RTT p50/p95 ms 5.43/6.06, 5.54/9.15, 5.28/11.8. [B] GTP-U: tested, tracer fresh in all 3 runs; `gtp && icmp` frames 76, 78, 78 (not de-duplicated; runs 2 and 3 in the same tracer file). Informational 1372-byte DF ping: 3/3 received in all 3 runs | `ping-1..3.txt`, `ping-pmtu-1..3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 | PASS | 15/15 scenario executions PASS with valid pcaps (V0-V2), 0 retries; Wilson 95% CI [0.796, 1.000]; reject cause 7 in 5/5, no accept for the reject UE; deregistration switch_off 0 and 0x46 in 5/5; no PDU session reject; every [B] item present in 15/15 (PFCP tied in all 10 initial-registration and deregistration pcaps); C2 not tested: no baseline | `suite-1..5.log`, `pcap-summary-1..5.json`, `pcap-summary.json`, `SHA256SUMS`, `pcaps/` (local); report-only `pcap-observations.json` |
| E4 | PASS | 10 panels / 18 targets; 17 with data; `pdusessioncreationfail` absent (allowed); reginitreq 2 -> 22 (+20, >= 15); reginitsucc 2 -> 16 (+14, >= 10); N3 in/out rate max in the E2 windows 0.10 / 0.16 / 0.34 per s; Panel 1 = 1 for every workload pod at the end (dbctl excluded); 6/6 Prometheus targets up; C3 not tested: no baseline | `grafana-panels.json`, `prom-targets.json`, `e4.json`, `compare.json` |
| E6(a) | PASS | 0 FAIL hits, 282 allowed hits, 0 other, at `bc3d615` (the 2 R2 attempt 1 hits are gone) | `wsl/grep.txt`, `wsl/allowlist-hits.txt`, `wsl/static.json` |
| E6(b) | kubeconfig part: match; overall **not met** | kubeconfig server host vs the Terraform state VM IPv4 (1 static address in `initialization`; Terraform outputs only `vm_id`): match, compared in memory; old host VM deleted, so R2b ran without it; but "R2 passes" is part of (b) and R2b failed (E1) | this README |
| E6(c) | not tested | R4 / T15a not run | |
| E7 allowlisted (2 of 2: R1, R2) | PASS | open TCP {22, 6443, 30030, 30090} = D7(a); 65531 filtered | `lan/scan-allow-2.txt`, `.json` |
| E7 non-allowlisted scan 1 (1 of 2; scan 2 is R3 after a reboot) | PASS | TCP 0 open of 65535 (65535 filtered); UDP 0 open, 8/8 open\|filtered; SCTP 0 open (2/2 filtered) | `lan/scan-nonallow-1.txt`, `.json` |
| E7 guard + NAD | PASS | from lab-ops' capture on this VM (20:12:05Z, `bc3d615`): `inet neoncore_guard` present, prerouting at mangle (-150), ct invalid drop, established/related accept, allow rule for 22/6443/30030/30090 from `<admin-ip>` only, final counter drop (134169 packets, which fits the laptop's full TCP scan being dropped); NAD resource type absent, 0 NADs, 4 K3s CRDs only (lab-ops and evaluator live 20:25:52Z); no pod requests a secondary network (14 + 3 pods, network-status only `cbr0` on `eth0`) | `lan/nft-ruleset.txt`, `lan/nft-check.json`, `lan/nad.json` |
| TB6 MTU (informational) | recorded | pods (evaluator, 20:26:21Z): gnb/upf/ue eth0 1450, upf ogstun 1500, ue uesimtun0 1400. Node: VM NIC 1500, flannel.1 1450, cni0 1450 from lab-ops' notes, **measured on the previous VM** (before from-zero attempt 2), not re-measured on this VM. Proxmox bridge 1500, no VLAN (owner-supplied, not measured). 1372-byte DF ping 3/3 x 3 | `mtu.txt`, `ping-n3.json`, `versions.txt` |
| C1-C4 | not tested: no baseline | C4 absolute part only: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `compare.json`, `versions.txt` |

## Observations (report-only, no threshold)
- **E1 failure detail.** `pods_check.py soak --duration-s 1500 --interval-s 60` took samples at offsets 0 to 1440 s and returned at 20:39:03Z (1500 s). The evaluator took pods-end at 20:41:08Z, 125 s later (its wait on the background soak was slower than the soak), so `evaluate` measured a 1630.4 s window that needs 26 samples. In R2 attempt 1, pods-end came 10 s after the soak and the window needed 24. Procedure note for the next run: take pods-end at once when the soak returns, or soak longer than the planned window. This is a procedure note, not a fix to `evals/`.
- **Tracer.** 0 restarts over the 1630 s window, through 3 E2 runs and 5 E3 suites; freshness "fresh" before the run, in each E2 run and after suite 5. The E1 failure mode of R2 attempt 1 (main capture stopped about 5 s after suite 1 started) did not recur.
- Run UE GUTI re-registration after deregistration: 5 of 5 deregistration pcaps (R2 attempt 1: 4 of 5; R1: 3 of 5). Every non-run NGAP id in these pcaps is that GUTI re-registration (its 5G-TMSI equals the one assigned to the run UE), so the background `ue` pod sent no N2 signalling in any pcap. One 5GMM STATUS #101 on the re-registration NGAP id (RAN 23) in deregistration `...-202418`. Auth failure #21 before every SUCI registration: 10/10 (as in R1 and R2, O-3). NEA0 in all 15 SMCs.
- Two registration-reject pcaps (`...-202025`, `...-202142`) hold 4 PFCP frames each; pcap_check reports their PFCP tie as "untied" (the other 3: "no-pfcp"). Report-only; the reject scenario has no PFCP requirement.
- E2 GTP-U counts per run (not de-duplicated): echo request 38/40/40, echo reply 38/38/38 frames, against 20 pings each seen twice. Report-only; the [B] item needs > 0.
- `capture_baseline.sh versions` printed "mtu_check: bad --label" again: its internal label contains parentheses, which `mtu_check.sh`'s label pattern rejects. Known since R2 attempt 1, not fixed (no `evals/` change during a run); the pod MTUs are in `mtu.txt` from a direct run, so nothing is missing.
- Raw scan XML (not committed; sha256 for provenance): laptop TCP `13f781bb...0d90b`, UDP `79e41b1b...b85b`, SCTP `49d5ae06...55a9`; control-machine allowlisted `4f3f695f...8ef8` (session scratchpad, deleted with the session).

## Not tested in R2b
- E1 re-evaluation with full sampling coverage (needs a full R2 rerun).
- C1-C4 (no baseline). E6(c) (R4). E7 non-allowlisted scan 2 (R3, after a reboot). Node MTUs on this VM (lab-ops values are from the previous VM). E8, E9 and E10 are not part of R2 (E10 was R1).
