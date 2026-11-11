# L0 run R1 (T8), Proxmox lab, first green deploy

Evaluator run, 2026-11-10. Plan `project/plans/L0.md` section 8 (approved hash 1310dd1c...).
Run window: 2026-11-10T05:12:56Z (epoch 1794287576) to 2026-11-10T05:58:21Z (epoch 1794290301), 2725 s.

## Provenance
- Git SHA at run start: 11aafc0 (later commits by other agents during the run: 5510a79, d82ee51, 0ef396d, 3f061d3; none touch evals/ or phase*/; each script records the SHA it saw).
- Working tree not clean: owner's uncommitted `.claude/hooks/gate.py` and `scripts/tests/test_gate.py` edits, an untracked approvals hash file, and this run's own evidence.
- Tool and image versions: `versions.txt`. Pcap sha256: `SHA256SUMS` (pcaps stay local, uncommitted).
- Cost estimate: $0. No API, GPU or cloud calls (budget.yaml caps 25 / 0 / 0 USD per month). Actual: $0.
- Baseline B: none (owner waiver 2026-11-10, WSL2 VM deleted). C1-C4 "not tested: no baseline"; [B] items reported, not required; registration-reject cause must be 7.

## Order and windows (epoch s)
| Step | Start | End |
|---|---|---|
| pods-start, soak start (2700 s, 60 s interval) | 1794287576 | 1794290301 (pods-end) |
| E10 negative + positive | 1794287590 | 1794287592 |
| E7 allowlisted scan (`nmap -Pn -sS -p-`, sudo, control machine) | 1794287688 | 1794287792 |
| E2 runs 1-3 | 1794287807 | 1794288020 |
| E3 suites 1-5 (back to back, check + copy after each) | 1794288040 | 1794288326 |
| E4 (Grafana NodePort, Prometheus NodePort) | after pods-end | |

The E7 scan ended 15 s before the first E2 run and did not overlap E2 or E3 (TA15). E3 pcaps show 0 frames from non-pod sources.

## Results
| Check | Result | Measured | Evidence |
|---|---|---|---|
| E1 | PASS | 2724.4 s soak, 45 samples; 17 pods; restart delta 0 for every pod; dbctl Succeeded; 0 leftover scenario-ue; C1/C4 not tested: no baseline | `pods-start.json`, `pods-end.json`, `soak.json`, `e1.json`, `workloads.json` |
| E2 | PASS (3/3) | 20/20, 20/20, 20/20 replies; N3 in +20/+20/+20, out +20/+20/+20; RTT p50/p95 ms 5.09/5.52, 5.14/5.50, 5.15/6.79. [B] GTP-U: not tested (tracer stalled) (erratum E-1/E-2; not required without B) | `ping-1.txt`..`ping-3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 | PASS | 15/15 scenario executions PASS with valid pcaps, 0 retries; Wilson 95% CI [0.796, 1.000]; reject cause 7 in 5/5; deregistration switch_off 0 and 0x46 in 5/5; every [B] item present in 15/15 (PFCP tied where expected) | `suite-1.log`..`suite-5.log`, `pcap-summary-1.json`..`-5.json`, `pcap-summary.json`, `SHA256SUMS`, `pcaps/` (local); report-only `pcap-observations.json` (erratum E-4) |
| E4 | PASS | 10 panels / 18 targets; 17 targets with data; `pdusessioncreationfail` absent (allowed); reginitreq +18 (>= 15), reginitsucc +11 (>= 10); N3 rate max in E2 windows 0.18 / 0.22 / 0.24 per s; Panel 1 = 1 for every workload pod; 6/6 Prometheus targets up; C3 not tested: no baseline. Counter breakdown: Observations O-4 (erratum E-3) | `grafana-panels.json`, `prom-targets.json`, `e4.json`, `compare.json` |
| E7 (allowlisted only) | PASS | open TCP {22, 6443, 30030, 30090} = D7(a) set; 65531 filtered; guard table checks pass; NAD: resource type absent, 0 NADs (judged PASS, see `lan/nad.json`) | `lan/scan-allow-1.txt`, `lan/scan-allow-1.json`, `lan/nft-ruleset.txt`, `lan/nft-check.json`, `lan/nad.json` |
| E10 | PASS | negative exit 1, mismatch named, no fingerprint printed, 0 terraform and 0 curl execve, PVEAPIToken count 0; positive exit 0, PVEAPIToken count 0 | `tls/negative.txt`, `tls/positive.txt` |
| C1-C4 | not tested: no baseline | | `compare.json` |

## Observations (not threshold failures)
- Tracer main capture stalled: the tracer's rotating tcpdump last wrote at 04:53:42Z; its current file was 0 bytes at 05:20Z. E2's [B] GTP-U item therefore measured 0 `gtp && icmp` frames in all 3 windows on a stale file (same sha256 in all 3 runs). **Corrected (erratum E-1):** a read of a stale file is not a measurement; the item is "not tested". Not required without B, but the tracer would not have recorded traffic for this run. phase6's per-scenario captures (E3) are separate tcpdump processes and were unaffected. The evaluator did not restart the tracer (lab change; E3's one allowed retry was not needed).
- `ping_check.sh` picks the tracer file with `ls -t`; when two files share an mtime it can pick the older one. Here both were stale, so it did not change the result.
- Multus runs but its NetworkAttachmentDefinition CRD is not installed.
- E7 non-allowlisted scan: not part of R1 (R2/R3; D7 host not named yet).

## Signalling observations (added 2026-11-10, erratum E-3; telco build review R1, TB7(a))
Facts from the 15 R1 pcaps, as found by the telco reviewer (`project/reports/L0/telco.md`, "## Build review (R1, 2026-11-10)", points 2 and 3, TB7 and TA20). The evaluator's report-only re-run of `pcap_check.py observe` on the same 15 pcaps (`pcap-observations.json`, commit 3b89588) gives the same counts. None of this changes a threshold. E2, E3 and E4 PASS stand.

- **O-1. The run UE re-registers on its own after deregistration, 3 of 5 times** (telco point 2, TB7). After the UE-originated, non-switch-off deregistration (switch_off 0), the scenario UE sends a new initial Registration request about 200 ms after the UEContextRelease. It is identified by 5G-GUTI, with the 5G-TMSI the AMF gave the run UE in its Registration accept. The runner did not trigger this. It is captured because the capture runs for about 2 s after the PASS line.
  - `deregistration-052112`, RAN_UE_NGAP_ID 6: InitialUEMessage at frame 545, 5G-TMSI 0xc000058f (same as the run UE's accept at frame 237). Authentication without resync, SMC NEA0, Registration accept (frame 721) with a new 5G-TMSI. The UE then sends **5GMM STATUS, cause #101** (message not compatible with the protocol state) at frame 727 instead of Registration complete.
  - `deregistration-052221`, RAN 10: the registration completes (frame 727: 0x43 + 0xc1), and a new PDU session is set up (O-2).
  - `deregistration-052411`, RAN 17: the same as RAN 6, with **5GMM STATUS #101** at frame 727 after the accept at frame 721 (05:24:18.228Z). The AMF releases RAN 17 with UEContextRelease Command, cause nas normal-release, at 05:24:48.240Z (`initial-registration-052444` frames 405/407). That is **30.01 s after the accept**, which fits T3550 (6 s) expiring 5 times and the AMF aborting the procedure. The telco reviewer inferred this from timing only (AMF log and retransmissions not seen).
  - Suites 3 and 5: no re-registration is visible.
  - Why UERANSIM answers #101 in 2 of the 3 cases: not determined.
  - pcap_check did not credit any of RAN 6/10/17 to the run UE. None carries a SUCI, so `run_ran_ue_ngap_ids` stays `["5"]`, `["9"]`, `["16"]` (telco point 2, "no false PASS").
- **O-2. Leftover PDU session** (telco point 2, TB7). On RAN 10 (`deregistration-052221`), the re-registered UE sets up a new PDU session for 10.45.0.7: PFCP 50/51 at frames 811/813, 0xc2 at 823, PFCP 52/53 at 839/841. The runner then deprovisions this subscriber. A matching release is not in the capture. This session is not used for the PFCP tie, which ties only 10.45.0.6 (RAN 9). Related (telco TA24, not verified): the UPF session gauge is 2 against the SMF's 1, at both the start and the end of the window.
- **O-3. Authentication failure #21 (synch failure) before every SUCI registration: 10/10** (telco TA20). Every first SUCI attempt gets Authentication request, then Authentication failure cause #21, then a second Authentication request and response (for example `initial-registration-052042` frames 227/229/263/265). The 3 GUTI re-registrations do not have it. `pcap-observations.json` shows `auth_failure_causes_run_ue` = ten 21s and no other cause. The cause is not verified. The telco reviewer's hypothesis is a subscriber document without `sqn`. It is harmless for L0 (the resync succeeds). For Stage 7, a healthy pcap already contains a 0x59, so a wrong-key fault label must require #20 (MAC failure), not "any 0x59".
- **O-4. E4 counter breakdown** (telco point 3, Open5GS v2.8.0 `src/amf/gmm-sm.c` as read by the telco reviewer: `RM_REG_INIT_REQ` is incremented for every initial-type Registration request before AUSF/UDM, so rejects count; `RM_REG_INIT_SUCC` is incremented on Registration complete, not on accept).
  - `reginitreq` **+18 = 15 + 3**: 15 scenario registrations (5 x initial-registration, registration-reject and deregistration), plus 3 GUTI re-registrations (RAN 6, 10, 17). The pcaps hold 18 InitialUEMessages, RAN IDs 3-20, each with a type-1 (initial) Registration request. The background UE contributes 0.
  - `reginitsucc` **+11 = 10 + 1**: 10 Registration completes (5 x initial-registration + 5 x deregistration), plus 1 from RAN 10. RAN 6 and 17 sent 5GMM STATUS #101 instead of Registration complete, so they are not counted.
  - The E4 thresholds (>= 15 and >= 10) are met either way. The R1 figures are explained only by counting the re-registrations.
- **O-5. TA21 report-only checks** (`pcap-observations.json`): NEA0 was selected in all 13 Security mode commands (10 SUCI + 3 GUTI). No authentication before the reject in 5/5. PFCP 52/53 is tied to the run UE's session in all 10 initial-registration and deregistration pcaps. Registration accept comes before complete wherever both are present (10/10). The background `ue` pod sent no N2 signalling in any pcap, so the background-UE exclusion has never been exercised against a second SUCI UE (telco TA22). It is covered only by unit tests with synthetic rows.

## Errata (2026-11-10, after the telco build review)
Nothing was re-measured. The R1 pass/fail files (`pcap-summary*.json`, `ping-n3.json`, `e4.json` and the rest) are unchanged.
- **E-1** `ping-gtpu.json`: the status of runs 1-3 changed from `"tested"` (0 frames) to `"not tested: tracer pcap stale (last write 04:53:42Z, before window)"`. The original fields are kept under `superseded_stale_file_read`, and the file has an `erratum` block. Reason: telco TB5. The tracer's main file was last written at 04:53:42Z, before every E2 window.
- **E-2** Results table, E2 row: the text "[B] GTP-U in tracer pcap: 0 frames (reported, not required; see observations)" now reads "[B] GTP-U: not tested (tracer stalled)". E2 stays PASS. GTP-U stays [B] (reported, not required). Making it required would be a plan amendment, which is the owner's decision.
- **E-3** Added "Signalling observations" O-1 to O-5 (telco TB7(a)) and pointers to them from the E3 and E4 rows. R1 originally reported E3 and E4 without these facts.
- **E-4** Added `pcap-observations.json`, a report-only re-run of `pcap_check.py observe` (commit 3b89588) on the 15 local R1 pcaps, with the same sha256 as `SHA256SUMS` (telco TB7(b)).
- **E-5** MTU (telco TB6): R1 recorded no MTU values and ran no `ping -M do -s 1372`. That stays "not tested" for R1. Pod-side values read later are in `../pre-r2/mtu.txt` (pre-R2 informational, not R1 evidence).
- Fixes for later runs (commit 3b89588): `ping_check.sh` labels GTP-U "not tested: tracer stale" when the tracer file is older than 30 s before the run, or older than the ping start after it. `ping_check.sh --pmtu` adds the informational path-MTU ping. `mtu_check.sh` records the pod MTUs and prints the node commands for lab-ops.
