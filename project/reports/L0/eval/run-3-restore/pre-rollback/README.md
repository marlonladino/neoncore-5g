# L0 run R3, pre-rollback E8 checks (T10 step 1)

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8, E8: "After `start.sh` (pre-rollback): E1, E2 (1 run) and E3 (1 suite) pass." Thresholds are the frozen E1-E3 thresholds; nothing was changed. This is not R3 itself: R3 runs in full after the owner's rollback to `golden-l0`, boot and laptop scan 2.
Run window (pods-start to pods-end): 2026-11-10T22:06:03Z (epoch 1794348363.41) to 22:23:04Z (epoch 1794349384.65), 1021.2 s.

**Verdict: PASS** (E1, E2 1/1, E3 3/3). C1-C4 "not tested: no baseline".

## Lab state before the run (from lab-ops, `813aaac`, `cd4fe99`; not measured by the evaluator)
- 21:56:02Z `stop.sh`; `golden-l0` snapshot taken with the VM shut down (the only snapshot).
- A first `start.sh` at 21:57:23Z failed at step 5 (UPF pod wait race in `infra/lab.sh`); fixed in `98f1e98` with tests.
- 22:02:19Z `stop.sh`; 22:03:02Z `start.sh`, rc=0 on the first try, all pods Ready at 22:04:11Z; `verify` passed.
- **Boot restarts (observation):** `pcf` restarted 2 times and `udr` 1 time during `start.sh` (lab-ops: same pods and counts on every start, startup ordering). They happened before this run. The evaluator's pods-start shows the same counts (pcf 2, udr 1, every other container 0), and pods-end shows the same counts, so the restart delta across the soak is 0. E1 measures the delta across the soak, so these boot restarts do not enter the threshold; they are recorded here as they are.
- smf and ue run on a new ReplicaSet revision (5) after `start.sh`'s recovery order (UPF -> SMF -> UE); report-only (C1 is not tested without a baseline).

## Procedure
- HEAD `cd4fe99` (full `cd4fe999f056cd2d876c3cf6ddce4e528a8a797f`), clean tree (0 porcelain lines) at 22:05:52Z. Code change since R2c (`9918be5`): `infra/lab.sh` and `infra/tests/test_lab.sh` (`98f1e98`), plus `project/` files. No `evals/` change.
- E1 chained as in R2c: one background invocation `pods_check.py snapshot` ; `pods_check.py soak --duration-s 1020 --interval-s 60` ; `pods_check.py snapshot`. Pre-check: 1020 s at 60 s gives 17 samples; a window of about 1021 s needs floor(1021 / 60) - 1 = 16, and the window is over 900 s (15 min).
- Tracer: `shareProcessNamespace: true`; freshness "fresh" before pods-start (22:05:58Z), inside the E2 run and after the E3 suite.
- Tools: tshark 4.2.2, kubectl client v1.37.2, server v1.36.6+k3s1, Python 3.12.3 (`versions.txt`). Cost: estimate $0, actual $0.
- Redaction: script outputs written with site values loaded under the lab env wrapper; the suite log and this README through redact.py without site values. Pcaps stay local (git-ignored), sha256 in `SHA256SUMS`.

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| pods-start | 1794348363 (22:06:03Z) | |
| soak (1020 s, 60 s interval, chained) | 1794348364 (first sample) | 1794349384 (last sample 22:22:04Z) |
| E2 run 1 (+ informational 1372-byte DF ping) | 1794348369 | 1794348443 |
| E3 suite 1 (+ check and copy) | 1794348453 | 1794348494 (suite end) |
| observations, workloads, versions, compare | after E3 | before pods-end |
| pods-end (same invocation as the soak) | 1794349384 (22:23:04Z) | |

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E1 | PASS | 17 soak samples (16 needed), window 1021.2 s (>= 900 s); gaps: start to first sample 0.8 s, max between samples 60.0 s, last sample to pods-end 60.4 s; all workload pods Running with all containers Ready at all 19 samples; no pod Pending/Failed/Unknown/CrashLoopBackOff; dbctl Job succeeded=1, pod Succeeded; 0 leftover scenario-ue pods; same 17 pods at start and end; restart delta 0 for every container (pcf 2 and udr 1 at both start and end, from boot); 0 sample read errors. C1 not tested: no baseline; C4 absolute part PASS | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json`, `compare.json` |
| E2 (1 run) | PASS | 20/20 replies; N3 in +20, out +20; RTT p50/p95 5.24/6.0 ms. [B] GTP-U: tested, tracer fresh, `gtp && icmp` 80 frames (40 request, 40 reply, not de-duplicated). Informational 1372-byte DF ping: 3/3 | `ping-1.txt`, `ping-pmtu-1.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 (1 suite) | PASS | 3/3 scenario executions PASS with valid pcaps (V0-V2), 0 retries; Wilson 95% CI for 3/3 [0.439, 1.000]; reject cause 7, no accept for the reject UE; deregistration switch_off 0 and 0x46; no PDU session reject; [B] items present (PFCP tied in the initial-registration and deregistration pcaps); 0 non-pod frames; suite wall time 41 s. C2 not tested: no baseline | `suite-1.log`, `pcap-summary.json`, `pcap-observations.json`, `SHA256SUMS`, `pcaps/` (local) |
| C1-C4 | not tested: no baseline | C4 absolute part: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `compare.json`, `versions.txt` |

## Observations (report-only)
- Boot restarts pcf x2 and udr x1, before the run (see above).
- Deregistration pcap: run UE GUTI re-registration present; one 5GMM STATUS #101 on a non-run NGAP id (the re-registration, as in R2b). Auth failure #21 before each SUCI registration (2/2). NEA0 in every SMC.
- `capture_baseline.sh versions` printed "mtu_check: bad --label" again (known, not fixed during a run).

## Not tested here
- E4, E7, E6 and MTU are not part of the pre-rollback check (they are in R3 after the rollback). C1-C4 (no baseline).
