### Metrics, thresholds, holdout and baseline

Author: evaluator. Fixed at PLAN time. After the plan is approved, builders (lab-ops, docs-writer, blog-writer, developer) cannot change anything in this section, in `evals/l0/` or in `project/reports/L0/eval/`. A change needs a plan amendment, which voids the approval.

#### 0. What does not apply to L0, and why
| Rule (WORKFLOW "Evaluation rules") | L0 | Reason |
|---|---|---|
| Holdout split | N/A | No model is trained, tuned or prompted in L0, so nothing can overfit a holdout. Stage 7 creates the first dataset and the first holdout. |
| LLM vs deterministic baseline | N/A | No LLM in the product. The "baseline" in L0 is the WSL2 lab's measured behavior (B, section 1). Proxmox must match it or beat it. |
| Leakage check | N/A | There are no model inputs. |
| Accuracy, confusion matrix, cost per query, model ID, prompt hash | N/A | No classifier and no paid calls. Pass rates still get Wilson 95% CIs (E3). |
| Cost estimate before paid runs | $0 | The evaluator scripts make no API calls. The estimate ($0) is checked against `project/budget.yaml` and written to `summary.md`. |
| Repeat runs for nondeterminism | Applies | It applies to scenarios, ping, soak and LAN scans (counts below). |
| Provenance | Applies | Every report records the git SHA (with `git status --porcelain`), tool versions (tshark, nmap, kubectl, k3s, terraform), and the sha256 of every pcap and baseline file (`SHA256SUMS`). These hashes take the place of a dataset hash. |

#### 1. Infrastructure baseline B (WSL2, captured before cutover)
**When:** before T4, so nothing built for Proxmox can influence it, and in any case before T9's `wsl --shutdown`. After T9 or T15a, B can never be recaptured. **This is a new task.** The current plan doesn't have it (see "Plan changes requested" at the end).

**How:** `evals/l0/capture_baseline.sh` runs against the running WSL2 lab. It is read-only except for the phase6 suite, which only provisions and deprovisions its own reserved test IMSIs (`99970000000990x`). It writes to `project/reports/L0/eval/baseline/`:

| ID | Captures | Files |
|---|---|---|
| B1 | Workloads and pods in `neoncore` and `monitoring`: kind, name, containers, image refs and imageIDs, Ready, phase, restarts. `dbctl` Job status. kube-system pods (informational) | `pods.json`, `workloads.json` |
| B2 | 3 × `kubectl -n neoncore exec deploy/ue -- ping -I uesimtun0 -c 20 -W 2 8.8.8.8`, with N3 GTP counter values before and after each run | `ping-{1,2,3}.txt`, `ping-n3.json` |
| B3 | 3 × `python3 -m phase6.tests.run_scenarios`. Pcaps are copied out at once, and each one is summarized by `evals/l0/pcap_check.py` (section 3) | `suite-{1,2,3}.log`, `pcaps/`, `pcap-summary.json` |
| B4 | Each target expression of each panel in dashboard uid `neoncore-5g` (10 panels, 17 targets), queried through Prometheus `/api/v1/query`: series count and label sets. Also `/api/v1/targets` health, and the Grafana dashboard JSON from `/api/dashboards/uid/neoncore-5g` | `prom-series.json`, `prom-targets.json`, `grafana-dashboard.json` |
| B5 | Versions: `k3s --version`, `open5gs-upfd -v` in the UPF pod, the UERANSIM version, the netshoot digest, `lsmod` for sctp/macvlan/ipvlan/iptable_nat | `versions.txt` |
| B6 | Timings: per-scenario durations from the suite logs, and ping RTTs | `timing.json` |
| — | Who ran it, when, git SHA, tool versions, sha256 of every file | `README.md`, `SHA256SUMS` |

**If B is degraded:** a WSL2 failure (for example a scenario fails, or GTP-U is missing) is recorded as it is. It never lowers a Proxmox threshold. Absolute thresholds apply whatever B shows. Baseline-conditional items (marked **[B]**) become required only when B shows them.

**If B can't be captured:** if WSL2 is already gone or broken, the comparison checks (C1–C4) are reported as "not tested: no baseline". The fallback references are the repo manifests, the dashboard JSON and `traces/rogue-ue-reject.pcap` (for registration-reject only). Absolute thresholds still apply. Each [B] item falls back to its stated default.

**How Proxmox results are compared with B** (`evals/l0/compare_baseline.py` → `compare.json` in each run folder):
- **C1 Workload set:** the set of (namespace, kind, workload name, container name, image ref) on Proxmox must equal B's.
  - Allowed differences: pod hash suffixes, IPs, node name, and the UPF imageID (rebuilt, not bit-identical; the tag must match).
  - If D9 pins the netshoot digest, it must equal B's digest.
  - Any missing or extra workload fails.
- **C2 Pcap content:** for each scenario, the Proxmox set of (protocol, message type) items from the section 3 list must be a superset of B's.
  - The registration-reject 5GMM cause must equal B's.
  - Extra message types are reported, not failed.
- **C3 Metric series:** every series B has for each dashboard target must exist on Proxmox. Series are matched by label set, without `instance`, pod-hash or IP labels. A missing series fails.
- **C4 Versions:** the K3s version equals B (D8). Open5GS reports 2.8.0, UERANSIM 3.3.0, and image tags equal B.
- **Informational:** scenario durations and ping RTT p50/p95 versus B. These have no threshold.

#### 2. Acceptance runs and repeat counts
| Run | When | Contents |
|---|---|---|
| R1 | T8, first green deploy | E1, E2, E3 (5 suites), E4, E7 (both scans), C1–C4, E10 |
| R2 | T9, after from-zero | E5, then E1, E2, E3 (5 suites), E4, E6, E7 (non-allowlisted scan, repeated), C1–C4 |
| R3 | T10, after rollback to `golden-l0` and boot | E8 = E1, E2, E3 (3 suites), E4, E7 (non-allowlisted scan, after a reboot), C1–C4 |
| R4 (only if T15a runs in L0) | After WSL2 is unregistered | E1, E2 (1 run), E3 (1 suite), E6(a) |

Each run writes to `project/reports/L0/eval/run-<n>-<tag>/`. All attempts are kept, including failed ones. Any failed threshold fails that run, and the fix is followed by a full rerun of that run. Partial reruns don't count.

#### 3. Valid pcap (used by E3 and B3; `evals/l0/pcap_check.py`)
**Tools:** tshark is run with `-o nas-5gs.null_decipher:TRUE`, because Open5GS uses NEA0, so the integrity-protected NAS messages can be decoded. If the installed tshark doesn't know that preference, the checker fails loudly and doesn't guess. The B pcaps and the Proxmox pcaps go through the same tshark version on the control machine.

A scenario pcap is **valid** only if all of these hold:
- **V0 Readable:**
  - The local file exists, its size is over 24 bytes, and its sha256 is recorded.
  - `capinfos -c` reports at least 1 packet.
  - `tshark -r` exits 0 with no "cut short" or "appears to be damaged" warning.
- **V1 Protocols present:** at least one `ngap` frame (SCTP) and at least one `nas-5gs` frame.
- **V2 Tied to this run:** a Registration request (5GMM type 0x41) whose SUCI MSIN (`nas-5gs.mm.suci.msin`) equals the run's suite MSISDN. The responses below must be on the same `ngap.RAN_UE_NGAP_ID` as that request. This makes sure the evidence comes from the scenario UE, not the background `ue` pod.
  - **initial-registration:** Registration accept (0x42) and Registration complete (0x43).
    - [B] PDU session establishment request/accept (5GSM 0xc1/0xc2).
    - [B] PFCP Session Establishment Request/Response (`pfcp.msg_type` 50/51).
  - **registration-reject:** Registration reject (0x44) and no Registration accept for that UE. The 5GMM cause is recorded and must equal B's (C2). With no B, it must equal the cause in `traces/rogue-ue-reject.pcap`.
  - **deregistration:** 0x41, 0x42 and 0x43 as above, then a UE-originating Deregistration request (0x45).
    - [B] Deregistration accept (0x46).
    - [B] NGAP UEContextRelease.
    - [B] PFCP Session Deletion (54/55).
- **V3 Default for missing B:** if B is missing, the [B] items are reported but not required. GTP-U is not required in scenario pcaps, because the scenarios carry no user data. It is checked in E2.

A run with an invalid pcap but a runner PASS counts as **not valid** (the WORKFLOW rule). It may be retried after a tracer restart. Retries are limited by E3.

#### 4. Exit criteria: checks, evidence and thresholds
| # | Exit criterion | Check (command or script) | Evidence under `project/reports/L0/eval/` | Pass threshold | Repeats |
|---|---|---|---|---|---|
| E1 | All `neoncore`/`monitoring` pods healthy, `dbctl` Completed | `evals/l0/pods_check.py`: `kubectl get pods,deploy,sts,ds,job -n neoncore -o json`, the same for `monitoring`, at the start and end of each run (≥ 15 min apart, with scenarios and ping in between), plus a sample every 60 s | `run-*/pods-start.json`, `pods-end.json`, `soak.json` | Every Deployment, StatefulSet and DaemonSet pod is Running with all containers Ready, at every sample. `dbctl` Job `succeeded=1` and its pod phase is Succeeded. No pod is Pending, Failed, Unknown or CrashLoopBackOff. No leftover `scenario-ue` pod at the end. Restart delta 0 for every container across the soak (≥ 15 min). C1 and C4 pass | Every run (R1–R4) |
| E2 | UE ping via `uesimtun0` | `evals/l0/ping_check.sh`: `kubectl -n neoncore exec deploy/ue -- ping -I uesimtun0 -c 20 -W 2 8.8.8.8` (the TUI's command with a larger count). The N3 counters are read from Prometheus before and after, waiting ≥ 2 scrape intervals (2 × 10 s). The tracer's current pcap is checked for GTP-U carrying ICMP | `run-*/ping-<k>.txt`, `ping-n3.json`, `ping-gtpu.json` | Each run gets ≥ 18/20 replies. `fivegs_ep_n3_gtp_indatapktn3upf` rises by ≥ 20 and `...outdatapktn3upf` by ≥ the number of replies received. [B] `gtp && icmp` frames in the tracer pcap during the window | 3 runs in R1, R2, R3; 1 in R4 |
| E3 | 3 phase6 scenarios pass with valid pcaps | `python3 -m phase6.tests.run_scenarios`, run back to back. After each suite, `evals/l0/pcap_check.py` checks the pcaps in `traces/scenario-runs/`, then copies them out (inside the 2 h retention window) | `run-*/suite-<k>.log`, `pcaps/`, `pcap-summary.json`, `compare.json` | R1 and R2: 15/15 scenario executions (5 suites × 3) PASS with valid pcaps, and C2 passes. R3: 9/9. Scenario-logic failures are never retried. At most 1 retry per run, and only for an invalid pcap caused by a tracer stall (restart the tracer, rerun that suite). More than 1 retry fails the run, because the tracer is unreliable. The report gives the pass rate with its Wilson 95% CI (15/15 gives a lower bound of 0.796; with this n, only "≥ ~80%" can be claimed) | 5 / 5 / 3 / 1 suites (R1–R4) |
| E4 | Grafana panels show data | `evals/l0/prom_check.py`. Through the Grafana API (NodePort 30030 from the control machine), `/api/dashboards/uid/neoncore-5g`, then `/api/ds/query` for each of the 17 targets over the run window. `/api/v1/targets` through Prometheus | `run-*/grafana-panels.json`, `prom-targets.json`, `compare.json` | The dashboard has exactly the 10 panels of `phase3/manifests/dashboards/neoncore-5g.json`. Each of the 17 targets returns ≥ 1 series with ≥ 1 non-null value. Every active Prometheus target is `up`. Panel 1 shows 1 for every `neoncore` pod. Over the run, AMF `rm_reginitreq` rises by ≥ 3 per suite and `rm_reginitsucc` by ≥ 2 per suite. N3 in/out `rate()` > 0 during the E2 window. C3 passes | Every run |
| E5 | One documented command rebuilds the lab from zero | T9. **Preconditions** are recorded before the start: clean commit (`git status --porcelain` empty, SHA logged), no VM with the VMID exists (GET `/cluster/resources`, result yes/no only), the state file is absent, and WSL2 is shut down (owner's timestamp). **Command:** `scripts/labenv infra/lab.sh up`, with start/end timestamps and exit code. **Idempotency:** a second `scripts/labenv infra/lab.sh up` right after | `fromzero/preconditions.txt`, `fromzero/lab-up.log` (redacted), `fromzero/timing.json`, `fromzero/idempotency.txt` | The first invocation exits 0 with no manual step between start and end. The owner attests, and the log shows no gap or manual command. Then R2 passes in full. Idempotency: Terraform plan has "0 to add, 0 to change, 0 to destroy" and Ansible has `changed=0` and `failed=0`. The `kubectl apply` output and the deliberate SMF/UE restart are informational. A failed first invocation fails E5. After a fix, E5 counts only after a new from-zero run (a new owner-approved destroy) at a clean commit | ≥ 1 successful from-zero. Every attempt is recorded |
| E6 | Nothing depends on WSL2/Windows | **(a) Static:** `evals/l0/wsl_grep.sh` runs `git grep -n -I -i -E 'wsl\|windows\|\.wslconfig\|/mnt/[a-z]/\|powershell\|\.exe\b'` over tracked files. **(b) Dynamic:** R2 ran with WSL2 shut down. The kubeconfig `server:` equals the Terraform VM address output (only "match" or "no match" is printed). **(c)** R4, if T15a runs | `wsl/grep.txt`, `wsl/allowlist-hits.txt`, `wsl/runtime.txt` | (a) Zero hits in executables and config: `*.sh`, `*.py`, `*.yaml`, `*.tf`, `*.cfg`, any file with a shebang or exec bit, `infra/**`, `scripts/**`, `start.sh`, `stop.sh`, `phase*/**`. Zero hits in `README.md` outside one heading whose title contains "History". Allowed (listed, not failed): `DEVLOG.md`, `project/**`, `.claude/**`, `docs/roadmap/**`, the migration post under `site/`, and that README History section. (b) R2 passes and the kubeconfig matches. (c) R4 passes if it runs, otherwise "not tested" | Once at R2. (a) is repeated at close on the final commit |
| E7 | LAN exposure closed | **From a non-allowlisted LAN host (owner runs it):** `nmap -Pn -sS -p- <vm>`, `nmap -Pn -sU -p 53,123,2152,4789,8472,8805,51820,51821 <vm>`, `nmap -Pn -sY -p 38412,9999 <vm>`. **From the control machine (allowlisted):** `nmap -Pn -sS -p- <vm>`. **On the VM:** `nft list ruleset` and `kubectl get network-attachment-definitions -A -o json`. `evals/l0/scan_parse.py` replaces addresses with `<vm>`/`<admin-cidr>` before anything is written | `lan/scan-nonallow-<k>.txt`, `lan/scan-allow-<k>.txt`, `lan/nft-ruleset.txt` (redacted), `lan/nad.json` | Non-allowlisted host: zero TCP ports `open` across 1–65535, zero UDP or SCTP ports `open` (`open\|filtered` is accepted and reported). Allowlisted host: the set of open TCP ports equals exactly {22, 6443, 30030, 30090} for D7(a), or {22} for D7(b). A missing or an extra port fails. No NetworkAttachmentDefinition puts a pod on the VM's LAN NIC, because that would bypass the host's nftables. If no non-allowlisted host is available, E7 is "not tested" and L0 cannot close on it | Non-allowlisted: 2 (R2, and R3 after a reboot, to prove the rules persist). Allowlisted: 2 (R1, R2) |
| E8 | `golden-l0` restore works | T10: `stop.sh`, snapshot, start, then R3 (`start.sh` order UPF → SMF → UE). Then the owner-approved rollback to `golden-l0`, boot, and R3 again | `run-3-restore/` (all E1–E4, E7 files), `restore/timing.json` | After `start.sh` (pre-rollback): E1, E2 (1 run) and E3 (1 suite) pass. After rollback: R3 passes in full | 1 rollback |
| E9 | Repo explains itself in 30 s | **(a) Static:** `evals/l0/readme_static.py` runs S1–S6 below. **(b) Reader test:** see section 5 | `readme30s/static.json`, `readme30s/reader-<k>.md`, `readme30s/score.json` | S1–S4 and S6 pass, and S5 passes on the file. Each reader scores ≥ 5/6 with Q1 correct | Static: at close on the final commit. Readers: ≥ 2 |
| E10 | TLS pin aborts on a wrong fingerprint (section 8, check 10) | `evals/l0/tls_negative.sh`: `scripts/labenv infra/lab.sh status` with `PVE_TLS_FINGERPRINT` overridden to a wrong value. It runs under `strace -f -e trace=execve` into a mode-600 scratch file. Only program basenames are extracted, then the raw file is deleted, so no argument (and so no token) is ever written. Positive control: the same command with the correct fingerprint | `tls/negative.txt`, `tls/positive.txt` | Negative: the exit code is non-zero, an abort message names the fingerprint mismatch, and no `terraform` or authenticated `curl` execve happens after the check (only the unauthenticated cert fetch). Positive: exits 0. If lab-ops' override doesn't reach the script through `labenv`, the result is "not tested" and gets reported | 1 negative + 1 positive (R1) |

#### 5. The 30-second test (E9)
**Static checks S1–S6 (deterministic):**
- **S1:** the README top section (title down to the first `## ` heading) has ≤ 120 words of prose, not counting image alt text, badge markup and URLs. Reasoning: 30 s at about 240 words per minute is 120 words.
- **S2:** the top section embeds `docs/media/tui-demo.gif`. `file` reports GIF image data, and the file is ≤ 5 MB.
- **S3:** a `## Roadmap` section lists W0, L0, 7, 8, 9, 10, 9B, 11 and 12, each with a status, and links `docs/roadmap/neoncore-roadmap.pdf` (the file exists).
- **S4:** `scripts/labenv infra/lab.sh up` appears verbatim in the top section or in the first section after it.
- **S5:** in `docs/github-metadata.md`, the description is ≤ 350 characters and there are ≤ 20 topics, each matching `^[a-z0-9][a-z0-9-]{0,49}$`. Whether they are applied on GitHub (`gh repo view --json description,repositoryTopics`) is checked only after T15b, otherwise "not tested (owner deferred)". `gh` is not installed on the control machine today.
- **S6:** every relative link and image in `README.md` resolves to a tracked file.

**Reader test:**
- **Readers:** at least 2 fresh readers, none of whom have seen this repo or worked on L0. Preferred: at least 1 human the owner recruits. Otherwise, fresh-context Claude sessions with no repo access, reported as such, and the human check is reported as "not tested".
- **Procedure:**
  1. The reader sees the rendered README top section and GIF for 30 s (a timer for humans; for models, only the top-section text plus the GIF's alt text and one representative frame).
  2. The page is closed.
  3. The reader answers from memory in writing.
- **Answer key (fixed now):**

| Q | Question | A correct answer must say |
|---|---|---|
| Q1 (mandatory) | What is this? | A 5G standalone core testbed or lab (Open5GS and/or UERANSIM, or "simulated gNB/UE") |
| Q2 | What is it for, or where is it going? | Generating labeled faults and/or an AI troubleshooter that finds them |
| Q3 | What does it run on? | A Proxmox VM, or single-node K3s/Kubernetes |
| Q4 | How would you bring it up? | One command (`lab.sh up`, or "a single script") |
| Q5 | What can you see or do with it? | Any two of: TUI, Grafana dashboards, packet captures/pcaps, scenarios |
| Q6 | What's done and what's planned? | That a roadmap or stages exist, with the lab done and the AI stages planned |

- **Scoring:** the evaluator scores against the key. Answers are stored verbatim. The docs-writer does not score or choose readers.

#### 6. Timing to record (informational, no thresholds)
- From-zero (E5): total wall time, plus a timestamp per `lab.sh up` step 1–9, including the UPF image build and the time until all pods are Ready.
- `start.sh` to all pods Ready. Rollback start to R3 green.
- Scenario duration and ping RTT, p50/p95 per run, next to B.
- **Why no threshold:** n = 1 for from-zero, the time is dominated by download speed and host hardware, and no exit criterion or roadmap item sets a time bound. A threshold would be arbitrary. Stage 7's generator throughput is a different matter: it may set one, based on these numbers.

#### 7. Evidence hygiene
- Addresses, hostnames, VMID, node name, CIDR and cert CN are replaced by placeholders before any file is written under `project/reports/L0/eval/`. Raw values are never written to the repo.
- The pcaps under `baseline/pcaps/` and `run-*/pcaps/` contain pod and node IPs and synthetic test IMSIs (PLMN 999-70). Whether they are published is the security-reviewer's call at close. Until then they stay local, uncommitted, and their sha256 stays in `SHA256SUMS`.
- Final verdict: `project/reports/L0/eval/summary.md` has one row per E1–E10 with PASS, FAIL or "not tested", the evidence path, and the run in which it was measured. Failures are published as they are.

#### Plan changes requested (lead and planner to decide; the evaluator does not edit the plan)
1. **New task (before T4, owner-assisted):** "WSL2 baseline capture B" with `evals/l0/capture_baseline.sh`. It must finish before T9 (`wsl --shutdown`) and before T15a. Who runs it inside WSL2 (owner, or the evaluator with WSL2 kubeconfig access) needs deciding. The evaluator does not contact the lab without that.
2. **T0/D12 installs on the control machine:** `tshark` (needed for V0–V3 and E2), `nmap` (E7 allowlisted scan) and `gh` (S5, after T15b). Today `tshark`, `nmap` and `gh` are not installed; `strace` and `nc` are.
3. **D7 addendum:** the owner provides a non-allowlisted LAN host with `nmap` for E7, used twice (R2, R3).
4. **T8/T9/T10 order** must allow R1–R3 as in section 2, including the post-reboot scan in R3. R4 is needed if T15a runs inside L0.
5. **E9:** the owner recruits ≥ 1 human fresh reader, or accepts model readers with the human check reported as "not tested".
