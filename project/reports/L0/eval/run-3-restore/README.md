# L0 run R3 (T10), after the rollback to `golden-l0`

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8, §2 R3 and E8: after the rollback to `golden-l0`, boot and `start.sh` (UPF -> SMF -> UE), R3 = E1, E2 (3 runs), E3 (3 suites), E4, E7 (non-allowlisted scan, after a reboot; guard table and unit present), C1-C4. Frozen thresholds, nothing changed. The pre-rollback E8 checks are in `pre-rollback/` (PASS, `f5f5d3f`).
Run window (pods-start to pods-end): 2026-11-10T23:07:44Z (epoch 1794352064.41) to 23:24:45Z (epoch 1794353085.61), 1021.2 s.

**R3 verdict: PASS.** E1, E2 3/3, E3 9/9, E4, E7 (non-allowlisted scan 2 after the reboot, guard table and unit after the reboot, NAD) pass. C1-C4 "not tested: no baseline".
**E8 verdict: PASS.** Pre-rollback E1, E2 (1 run) and E3 (1 suite) passed (`pre-rollback/`); 1 owner rollback to `golden-l0`; R3 passes in full after it (this run).

## Rollback and boot (not measured by the evaluator)
- Rollback: Proxmox task `qmrollback` to `golden-l0`, status "stopped: OK", 2026-11-10T22:32:00Z to 22:32:01Z (owner-supplied from the Proxmox task log; `project/notes/L0.md`, `2483104`).
- Boot: the owner booted the VM and ran `start.sh`; guest boot 22:33:56 (lab-ops `uptime -s`), all neoncore pods started at about 22:34:12Z; the lead checked node Ready and UE ping 3/3.
- **Boot restarts (observation):** during `start.sh`, `gnb` restarted 1 time, `pcf` 1 time and `udr` 2 times (pre-rollback start: pcf 2, udr 1; the set and counts vary per boot). They happened before this run. pods-start and pods-end show exactly these counts and 0 for every other container, so the restart delta across the soak is 0; they are recorded here as they are.
- `golden-l0` is the only snapshot (lab-ops snapshot list at 23:07:55Z: golden-l0 plus the "current" pseudo-entry).
- smf and ue run on new ReplicaSets after `start.sh`'s recovery order; report-only (C1 not tested).

## Provenance
- Git SHA at run start: `f5f5d3f` (clean tree, 0 porcelain lines at 23:07:32Z). During the run, the lead/lab-ops committed `c675b62` and `2483104`; both change only `project/notes/L0.md` (checked: `git diff --name-only f5f5d3f..2483104`). No `evals/` change since R2c; the code change since R2c is `infra/lab.sh` and its tests (`98f1e98`).
- Tools: tshark 4.2.2, nmap 7.993 (owner's laptop, as reported in its XML), kubectl client v1.37.2, server v1.36.6+k3s1, Python 3.12.3 (`versions.txt`). Cost: estimate $0, actual $0.
- E1 chained as in R2c: one background invocation `pods_check.py snapshot` ; `pods_check.py soak --duration-s 1020 --interval-s 60` ; `pods_check.py snapshot`. Pre-check: 17 samples, need floor(~1021 / 60) - 1 = 16; window > 900 s.
- Tracer: `shareProcessNamespace: true`; freshness "fresh" before pods-start (23:07:39Z), inside each E2 run and after E3 suite 3 (23:14:05Z). lab-ops: tracer PID 1 `/pause`, 0 restarts, started 22:34:12Z.
- Redaction: script outputs written with site values loaded under the lab env wrapper. Suite logs, `lan/nft-ruleset.txt` (from lab-ops' already-redacted notes), `lan/nad.json`, `lan/guard-after-reboot.json` and this README through redact.py without site values. Pcaps stay local (git-ignored), sha256 in `SHA256SUMS`. Raw scan XML is not committed.

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| Rollback (owner) | 22:32:00Z | 22:32:01Z |
| Guest boot, `start.sh` | 22:33:56Z (boot) | pods started about 22:34:12Z |
| E7 non-allowlisted scan 2 (owner, LAN laptop, after the reboot; TCP, UDP, SCTP) | 22:35:50Z (XML; owner 22:35:41Z) | 23:01:41Z (XML; owner 23:01:50Z); TCP 1473.53 s, UDP 3.14 s, SCTP 2.26 s |
| lab-ops read-only capture (guard unit/table, ruleset, NAD, tracer) | 23:07:55Z | |
| pods-start | 1794352064 (23:07:44Z) | |
| soak (1020 s, 60 s, chained) | 1794352065 (first sample) | 1794353085 (last sample 23:23:45Z) |
| E2 runs 1-3 (+ informational 1372-byte DF ping each) | after pods-start (ping windows from 1794352094) | 1794352295 |
| E3 suites 1-3 (check + copy after each) | 1794352319 | 1794352443 |
| scan parse, nft check, NAD live check (23:14:53Z), workloads, MTU, versions | after E3 | before pods-end |
| pods-end (same invocation as the soak) | 1794353085 (23:24:45Z) | |
| E4 (Grafana NodePort, Prometheus NodePort), window = pods-start to pods-end | after pods-end | |

The laptop scan ended before the run window, so it overlapped neither E2 nor E3. All 3 XMLs target the kubeconfig server host (checked in memory, "match" only). All 9 E3 pcaps show 0 frames from non-pod sources. The lab-ops capture at 23:07:55Z fell inside the run window, before the E2 ping windows; it is read-only.

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E8 | **PASS** | pre-rollback E1/E2/E3 PASS (`f5f5d3f`); rollback to `golden-l0` (owner, "stopped: OK"); R3 PASS in full | `pre-rollback/README.md`, this README |
| E1 | PASS | 17 soak samples (16 needed), window 1021.2 s (>= 900 s); gaps 0.8 s to the first sample, max 60.0 s between samples, 60.4 s last sample to pods-end; all workload pods Running and Ready at all 19 samples; no pod Pending/Failed/Unknown/CrashLoopBackOff; dbctl Job succeeded=1, pod Succeeded; 0 leftover scenario-ue pods; same 17 pods at start and end; restart delta 0 for every container (gnb 1, pcf 1, udr 2 at both start and end, from boot); 0 sample read errors. C1 not tested: no baseline; C4 absolute part PASS | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json`, `compare.json` |
| E2 | PASS (3/3) | 20/20, 20/20, 20/20 replies; N3 in +20/+20/+20, out +20/+20/+20; RTT p50/p95 ms 5.26/9.06, 5.15/5.49, 5.0/5.4. [B] GTP-U tested, tracer fresh in all 3 runs: `gtp && icmp` 80, 80, 80 frames (40 request, 40 reply each, not de-duplicated). Informational 1372-byte DF ping: 3/3 in all 3 runs | `ping-1..3.txt`, `ping-pmtu-1..3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 | PASS (9/9) | 9/9 scenario executions PASS with valid pcaps (V0-V2), 0 retries; Wilson 95% CI [0.701, 1.000]; reject cause 7 in 3/3, no accept for the reject UE; deregistration switch_off 0 and 0x46 in 3/3; no PDU session reject; every [B] item present (PFCP tied in all 6 initial-registration and deregistration pcaps); suite wall times 40, 41, 40 s. C2 not tested: no baseline | `suite-1..3.log`, `pcap-summary-1..3.json`, `pcap-summary.json`, `pcap-observations.json`, `SHA256SUMS`, `pcaps/` (local) |
| E4 | PASS | 10 panels / 18 targets; 17 with data; `pdusessioncreationfail` absent (allowed); reginitreq 1 -> 13 (+12, >= 9); reginitsucc 1 -> 9 (+8, >= 6); N3 in/out rate max in the E2 windows 0.16/0.16, 0.36/0.36, 0.16/0.16 per s; Panel 1 = 1 for every workload pod at the end (dbctl excluded); 6/6 Prometheus targets up; C3 not tested: no baseline | `grafana-panels.json`, `prom-targets.json`, `e4.json`, `compare.json` |
| E7 non-allowlisted scan 2 (2 of 2, after the reboot) | PASS | TCP 0 open of 65535 (65535 filtered, no-response); UDP 0 open, 8/8 open\|filtered; SCTP 0 open (2/2 filtered) | `lan/scan-nonallow-2.txt`, `.json` |
| E7 guard after the reboot (S-B7) | PASS | lab-ops capture 23:07:55Z, after the 22:33:56 boot (`c675b62`): `neoncore-guard.service` enabled and active; `nftables.service` masked (inactive); table `inet neoncore_guard` present: prerouting at mangle (-150), `iifname != "eth0"` accept, ct invalid drop, established/related accept, tcp 22/6443/30030/30090 new from `<admin-ip>` accept, final counter drop (133011 packets, which fits the laptop's full TCP scan after the boot); `scan_parse.py nft` on the full ruleset: PASS | `lan/guard-after-reboot.json`, `lan/nft-ruleset.txt`, `lan/nft-check.json` |
| E7 NAD | PASS | evaluator live 23:14:53Z and lab-ops 23:07:55Z: resource type absent, 0 NADs, 4 K3s CRDs only, 0 API resources matching; 0 pods request a secondary network; gnb/upf/ue interfaces only lo, eth0 (+ ogstun / uesimtun0) | `lan/nad.json` |
| E7 allowlisted | not part of R3 | 2 of 2 done (R1, R2c) | `../run-2c-fromzero/lan/scan-allow-2.txt` |
| TB6 MTU (informational) | recorded | pods (23:14Z): gnb/upf/ue eth0 1450, upf ogstun 1500, ue uesimtun0 1400. Node: not re-measured after the rollback (lab-ops, same VM before the rollback, `4387a7f`: 1500/1450/1450). Proxmox bridge 1500, no VLAN (owner-supplied). 1372-byte DF ping 3/3 x 3 runs, plus 3/3 in `versions.txt` | `mtu.txt`, `ping-n3.json`, `versions.txt` |
| C1-C4 | not tested: no baseline | C4 absolute part: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `compare.json`, `versions.txt` |

## Observations (report-only, no threshold)
- Boot restarts gnb x1, pcf x1, udr x2, before the run (see above). Across three starts (21:57Z, 22:03Z, after the rollback) pcf and udr restarted every time; gnb only after the rollback.
- After the rollback, only the `dbctl` pod (created before the snapshot) carries a `k8s.v1.cni.cncf.io/network-status` annotation; the 13 pods started after the rollback carry none (R2b/R2c: 13 of 14). No pod requests a secondary network, and the pod interfaces are as expected, so the E7 NAD reading does not change. Not investigated.
- The AMF registration counters started at 1 after the boot (fresh AMF process), so reginitreq/succ deltas are from a low base; the E4 rule is on the increase.
- Run UE GUTI re-registration after deregistration: 3 of 3 deregistration pcaps; every non-run NGAP id is that re-registration. One 5GMM STATUS #101 on the re-registration NGAP id (deregistration `...-231306`), as seen in R2b and pre-rollback. Auth failure #21 before every SUCI registration: 6/6. NEA0 in all 6 SMCs. The 3 reject pcaps hold no PFCP ("no-pfcp").
- `capture_baseline.sh versions` printed "mtu_check: bad --label" again (known, not fixed during a run).
- Raw laptop scan XML (not committed; sha256 prefix): TCP `5f212a5e...`, UDP `d5c01ab0...`, SCTP `a2e1b424...`.

## Not tested in R3
- C1-C4 (no baseline). Node MTUs after the rollback (not re-measured). Proxmox bridge MTU (owner-supplied). Per-scenario durations (suite wall times only). The rollback task record and boot time are owner/lab-ops evidence, not evaluator measurements. E5, E6, E9 and E10 are not part of R3.
