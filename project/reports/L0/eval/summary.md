# L0 evaluator summary

Written by the evaluator. The harness refused the evaluator's own file write, so the lead saved the text in project/notes/ and the owner copied it here. Numbers are the evaluator's; the verdict wording follows the owner's ruling of 2026-11-11 (see Verdict).

Evaluator, 2026-11-11. Plan `project/plans/L0.md` section 8 (approved hash 1310dd1c..., E4 amendment). Thresholds were fixed at PLAN time and not changed. Every row below is taken from committed evidence under `project/reports/L0/eval/`. The only new measurement in this summary is the close-time E6(a) grep (`close/wsl/`, commit `8d4b3dd`). Failed attempts are kept and listed.

## Verdict

**L0 closes with deviations.** E1-E8 and E10 PASS in their final runs. E9(b) FAILED the evaluator's pre-registered rule (all 3 readers must score >= 5/6 with Q1 correct) and PASSES on the plan's threshold as the owner ruled on 2026-11-11 ("Readers: >= 2" means at least 2 readers pass): opus and sonnet passed strictly in both attempts. E6(c) is not tested (R4/T15a not run). C1-C4 are not tested (baseline B waived). E9(a) static PASS.

**Owner ruling (2026-11-11):** the plan's E9 threshold is read as at least 2 readers pass. The README was not re-tuned and the reader test was not re-keyed. The evaluator's original all-3 verdict (FAIL) stays recorded as the pre-registered result. Caveats: attempt 2 is not independent of attempt 1; the strict reading for attempt 1 was chosen after the answers were seen; haiku failed Q1 both times; model readers only (D15); no repeat runs.

## Exit criteria and comparison checks

| ID | Final result | Run (id, commit) | Measured | Evidence (under `project/reports/L0/eval/`) |
|---|---|---|---|---|
| E1 pods healthy | **PASS** (R1, R2c, R3) | R1 `11aafc0`; R2c `4387a7f`; R3 `f5f5d3f` | R1: 45 samples over 2724.4 s. R2c: 25 samples (24 needed) over 1501.5 s. R3: 17 samples (16 needed) over 1021.2 s. Restart delta 0 in all three. dbctl Succeeded. 0 leftover scenario-ue pods. Failed attempts: R2 (tracer restart delta 1) and R2b (sampling coverage 25 < 26, evaluator procedure) | `run-1-proxmox/e1.json`, `run-2c-fromzero/e1.json`, `run-3-restore/e1.json` (plus `pods-start.json`, `pods-end.json`, `soak.json`); `run-2-fromzero/`, `run-2b-fromzero/` |
| E2 UE ping | **PASS** (3/3 in R1, R2c, R3) | as E1 | 20/20 replies in every run. N3 in +20 and out +20 in every run. [B] GTP-U: not tested in R1 (tracer stalled, erratum E-1). Tested in R2c, raw counts not de-duplicated (80, 80, 20 frames; run 3 straddled a rotation) and R3 (80, 80, 80) | `run-*/ping-1..3.txt`, `ping-n3.json`, `ping-gtpu.json` |
| E3 scenarios + valid pcaps | **PASS** | R1 15/15; R2c 15/15; R3 9/9; R3 pre-rollback 3/3 | 0 retries in every run. Wilson 95% CI: 15/15 [0.796, 1.000] (R1, R2c), 9/9 [0.701, 1.000] (R3), 3/3 [0.439, 1.000] (pre-rollback). Reject cause 7 in every reject pcap. Deregistration 0x46 present every time | `run-*/pcap-summary.json`, `suite-*.log`, `SHA256SUMS`, `pcap-observations.json` |
| E4 Grafana panels | **PASS** (R1, R2c, R3) | as E1 | 10 panels / 18 targets, 17 with data (`pdusessioncreationfail` absent, which is allowed). 6/6 Prometheus targets up. reginitreq/reginitsucc deltas: R1 +18/+11, R2c +20/+15, R3 +12/+8 (thresholds 15/10, 15/10, 9/6) | `run-*/e4.json`, `grafana-panels.json`, `prom-targets.json` |
| E5 from zero | **PASS** (attempt 2) | from-zero attempt 2 at `b9377fc`, then R2c PASS | Run 3 exit 0 in 396 s with no manual step (owner attests). Idempotency 0/0/0 and changed=0. Attempt 1 (`fromzero/`) did not pass because R2 failed. Open for the owner: preconditions recorded at `b9c421d`, run at `b9377fc` (the difference is the evidence file only) | `fromzero-2/README.md`, `timing.json`, `idempotency.txt`, `attestation.txt`; `fromzero/` |
| E6(a) static grep | **PASS** | R2c at `4387a7f`; **close at `24fbf52`** | Close run: 0 FAIL hits, 1163 allowed, 0 other (porcelain 3: other agents' uncommitted edits to `project/STATUS.md` and `project/reports/L0/{security,telco}.md`, all allowed paths). R2c: 0 / 571 / 0. R2 failed with 2 hits, both later fixed | `close/wsl/static.json`, `close/wsl/grep.txt`, `close/wsl/allowlist-hits.txt`; `run-2c-fromzero/wsl/`; `wsl/` (R2) |
| E6(b) runtime | **PASS** | R2c | kubeconfig server host matches the Terraform state VM address (compared in memory, only match/no match printed). The old host VM was deleted, and R2 passed in full (R2c) | `run-2c-fromzero/README.md`; `wsl/runtime.txt` (R2 attempt) |
| E6(c) R4 | **not tested** | none | R4/T15a not run in L0 | none |
| E7 LAN exposure | **PASS** | allowlisted: R1, R2c; non-allowlisted: R2c (scan 1), R3 after reboot (scan 2) | Allowlisted 2 of 2: open TCP set {22, 6443, 30030, 30090}, equal to D7(a). Non-allowlisted 2 of 2: TCP 0 open of 65535, UDP 0 open (8/8 open\|filtered), SCTP 0 open. Guard table and unit present after the reboot. NAD resource type absent, 0 NADs. The scan host was the owner's LAN laptop | `run-1-proxmox/lan/scan-allow-1.*`, `run-2c-fromzero/lan/scan-allow-2.*`, `run-2c-fromzero/lan/scan-nonallow-1.*`, `run-3-restore/lan/scan-nonallow-2.*`, `run-3-restore/lan/guard-after-reboot.json`, `run-*/lan/nft-check.json`, `nad.json` |
| E8 golden-l0 restore | **PASS** | pre-rollback at `cd4fe99` (evidence `f5f5d3f`); R3 at `f5f5d3f` | Pre-rollback E1, E2 1/1 and E3 3/3 PASS. 1 owner rollback ("stopped: OK", task record `2483104`). R3 PASS in full | `run-3-restore/pre-rollback/README.md`, `run-3-restore/README.md` |
| E9(a) static S1-S6 | **PASS** | attempt 2 at `a59970b` (README commit; static run at `fb1bab2`); attempt 1 PASS at `100fd30` | S1 59 prose words (<= 120). S2 GIF 3084694 bytes. S3 9/9 stages with status, PDF linked. S4 present. S5 297 chars, 16 topics; "applied on GitHub" not tested (T15b). S6 12 links resolved, 0 unresolved (attempt 1: 11). Not re-run on the close commit, but `git diff a59970b 24fbf52` is empty for `README.md`, `docs/media/tui-demo.gif`, `docs/github-metadata.md` and `docs/roadmap/` | `readme30s/run2/static.json`; `readme30s/static.json` |
| E9(b) reader test | **PASS on the plan's "at least 2 readers" threshold (owner ruling 2026-11-11); FAIL under the evaluator's pre-registered all-3 rule** | attempt 1 at `100fd30` (`8b9cab9`); attempt 2 at `a59970b` (pre-registered `fb1bab2`, evidence `fed9726`) | Threshold: each reader >= 5/6 with Q1 correct. All 3 pre-registered readers count (see "Verdict wording"). Strict: attempt 1 opus 5/6, sonnet 5/6, haiku 4/6 (Q1 wrong). Attempt 2 opus 6/6, sonnet 6/6, haiku 4/6 (Q1 wrong again, Q6 0). Lenient (sensitivity only): 6/6 for all readers in both attempts. Attempt 2 is **not independent**: the README sentence added in `a59970b` was written knowing the attempt-1 answers and aimed at Q6. Attempt 1's strict/lenient reading was chosen after the answers were seen (disclosed). Attempt 2's was pre-registered. Model readers only. Human reader: not tested (D15) | `readme30s/score.json`, `readme30s/reader-1..3.md`; `readme30s/run2/preregistration.md`, `score.json`, `reader-1..3.md` |
| E10 TLS pin | **PASS** | R1 `11aafc0` | Negative: exit 1, mismatch named, 0 terraform and 0 curl execve after the check, PVEAPIToken count 0. Positive: exit 0 | `run-1-proxmox/tls/negative.txt`, `positive.txt` |
| C1 workload set | **not tested: no baseline** | none | Baseline B was waived by the owner on 2026-11-10 (WSL2 VM deleted) | `run-*/compare.json` |
| C2 pcap content | **not tested: no baseline** | none | Fallback rule held: reject cause 7, equal to `traces/rogue-ue-reject.pcap` | `run-*/compare.json`, `pcap-summary.json` |
| C3 metric series | **not tested: no baseline** | none | none | `run-*/compare.json` |
| C4 versions | **not tested: no baseline** | none | Absolute part only, which PASSES: Open5GS v2.8.0, UERANSIM v3.3.0, K3s v1.36.6+k3s1 | `run-*/compare.json`, `versions.txt` |

## Run log (all attempts kept)

| Run | Folder | Commit | Verdict |
|---|---|---|---|
| R1 | `run-1-proxmox/` | `11aafc0` (evidence `b83738e`, errata `0b92f6b`) | PASS |
| R2 (from zero, attempt 1) | `run-2-fromzero/`, `fromzero/` | see README | FAIL: E1 tracer restart and E6(a) 2 hits |
| R2b (from zero, attempt 2) | `run-2b-fromzero/`, `fromzero-2/` | `bc3d615` | FAIL: E1 sampling coverage only |
| R2c (full rerun, same VM) | `run-2c-fromzero/` | `4387a7f` (evidence `9918be5`) | PASS, which completes E5 |
| R3 pre-rollback | `run-3-restore/pre-rollback/` | `cd4fe99` (evidence `f5f5d3f`) | PASS |
| R3 | `run-3-restore/` | `f5f5d3f` (evidence `0fe31bb`) | PASS (E8 PASS) |
| E9 attempt 1 | `readme30s/` | `100fd30` (evidence `8b9cab9`) | static PASS, readers FAIL strict |
| E9 attempt 2 | `readme30s/run2/` | `a59970b` / `fb1bab2` (evidence `fed9726`) | static PASS, readers FAIL strict |
| E6(a) close | `close/wsl/` | `24fbf52` (evidence `8d4b3dd`) | PASS |
| R4 | none | none | not run |

## Close-time E6(a) run

- Command: `evals/l0/wsl_grep.sh --out-dir project/reports/L0/eval/close/wsl`, run directly on the control machine (not under the lab env wrapper), 2026-11-11T15:27:11Z. Exit 0, output `E6(a) PASS: fail=0 allowed=1163 other=0`.
- HEAD `24fbf52e4608399006ceec23a2af6e56d97fbb7f`, porcelain 3. `git grep` reads the working-tree content of tracked files, so the 3 uncommitted files were scanned. All 3 are under `project/**`, an allowed path. Redaction ran through redact.py with no site values (structural and address redaction only). The files hold grep hits, not lab values.
- Allowed hits rose from 571 (R2c) to 1163. Most of the increase comes from committed evidence that quotes earlier hit lists (`run-2c-fromzero/wsl/allowlist-hits.txt` 571 lines, `run-2b-fromzero/...` 282, `wsl/...` 137). 8 allowed hits are marked "(allowed, executable)". They are `.claude/hooks/gate.py:337`, which is the eval script name in the gate's allowlist, and quotes of that line in earlier evidence. `.claude/**` is allowed by the plan.
- Scope: a later commit that only touches `project/**` cannot change the result. A later commit that touches any other path needs E6(a) re-run on the final commit.

## Cost and latency

- Estimate before the paid E9 sessions: under $0.10 per attempt. Abort rule: more than $0.10 in a single session. It was not triggered.
- Lab runs R1-R3, E5, E6, E7, E8, E10 and the E9 static check: estimate $0, actual $0 (no API, GPU or cloud calls).
- E9(b) reader sessions, CLI-reported Claude Code session usage (outside `budget.yaml` per plan section 10; even if counted, far below the $25/month API cap, and the ledger is empty):

| Attempt | opus | sonnet | haiku | Total |
|---|---|---|---|---|
| 1 | $0.0302906 | $0.0163313 | $0.00079763 | $0.04741953 |
| 2 | $0.031926 | $0.017259 | $0.0008139 | $0.0499989 |

  - Both attempts together: $0.09741843.
- E9(b) answer-turn latency (turn 2), n = 3 per attempt. Attempt 1: 4.564, 5.534, 6.48 s (p50 5.534 s; nearest-rank p95 is the max, 6.48 s). Attempt 2: 4.306, 6.521, 6.528 s (p50 6.521 s; p95 6.528 s). With n = 3 the p95 is just the maximum.
- Lab timings (informational, no threshold): E5 from-zero run 3 took 396 s wall and 342 s to all workload pods Ready (`fromzero-2/timing.json`). Suite wall times were 41-43 s in R2c and 40-41 s in R3. E2 RTT p50/p95 per run is in each run README (for example R2c 5.06/6.79, 5.14/6.05, 5.26/11.4 ms).

## Provenance

- Lab-run commits are in the run log above. Each run README records the porcelain state, tool versions (tshark 4.2.2, nmap 7.94SVN control machine / 7.993 laptop, kubectl v1.37.2 client, K3s v1.36.6+k3s1, Python 3.12.3) and `SHA256SUMS` for every pcap. The pcaps stay local and uncommitted. These hashes stand in for a dataset hash.
- E9 model IDs: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`. Prompt hashes (turn text sha256): attempt 1 `293866a4...91f3`, attempt 2 `bcafd56c...3460`. Input jsonl sha256: attempt 1 `67f5b8f7...7e80`, attempt 2 `3ce5020a...457b`. README sha256: attempt 1 `2f5485c6...a089`, attempt 2 `6a50def2...422d`. GIF frame 250 PNG `43db9481...c44a` is the same in both attempts. Full values are in the two `score.json` files.
- N/A for L0 (plan section 8.0): holdout, leakage check, LLM-vs-deterministic baseline, accuracy and confusion matrix. L0 has no product model.

## Not tested

- C1-C4 (baseline B waived, no WSL2 baseline). Every [B] item was reported, not required.
- E2 [B] GTP-U in R1 (tracer stalled, erratum E-1).
- E6(c) and the whole of R4 (T15a not run in L0).
- E9(b) with a human reader (D15: model readers only).
- E9(b) repeat runs for nondeterminism (one run per reader per attempt).
- E9(b) independent second attempt (attempt 2 followed a README change aimed at Q6).
- E9(a) S5 "applied on GitHub" (owner deferred until T15b; `gh` not installed).
- E9(a) static re-run on the close commit (not re-run; inputs unchanged since `a59970b`, see the E9(a) row).
- MTU in R1 (no values, no 1372-byte DF ping).
- Node MTUs after the rollback (not re-measured).
- Proxmox bridge MTU (owner-supplied, not measured).
- Per-scenario durations (the suite logs have no per-line timestamps; only suite wall times).
- Exclusion of the background UE against a second SUCI UE (never exercised live; unit tests only, telco TA22).
- Causes of these report-only observations, not investigated:
  - Auth failure #21 before every SUCI registration.
  - 5GMM STATUS #101 on GUTI re-registration.
  - UPF/SMF session gauge mismatch (telco TA24).
  - Only `dbctl` carries a network-status annotation after the rollback.
  - Varying boot restarts (pcf, udr, gnb).
- Rollback task record and guest boot time are owner/lab-ops evidence, not evaluator measurements.
- The `capture_baseline.sh versions` "bad --label" message is a known bug and was not fixed. The pod MTUs were captured separately.
