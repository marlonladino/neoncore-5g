# L0 telco review

## Plan review

Reviewer: telco-reviewer. Date: 2026-11-09. Object: draft `project/plans/L0.md` (untracked, unapproved).
The lab was not contacted.

**How I checked.** tshark/capinfos are **not installed** on the control machine (`command -v` empty; apt candidate is tshark 4.2.2 on Ubuntu 24.04.5). So I could not run `tshark -r`. I read `traces/rogue-ue-reject.pcap` with a small read-only Python decoder (pcap header, SLL2, IPv4, SCTP DATA chunks, plain-NAS byte patterns). Its results are labelled "(custom decoder, not tshark)". Wireshark field names come from the Wireshark display filter reference (dfref pages for `nas-5gs` and `ngap`). Open5GS metric behaviour comes from the v2.8.0 source (`src/amf/gmm-sm.c`, `src/smf/metrics.c`, `src/pcf/metrics.c`). Clause numbers come from my own knowledge of the Rel-17 specs (TS 24.501 V17.x, TS 23.502 V17.x, TS 38.413/38.412 V17.x, TS 29.244 V17.x, TS 29.281 V17.x). **I did not re-read the spec text in this review**, so treat clause numbers as "not verified against the document".

### Evidence from `traces/rogue-ue-reject.pcap` (custom decoder, not tshark)
- 582 frames, link type 276 (Linux SLL2, from `tcpdump -i any`). Protocol mix: 48 SCTP, 40 PFCP (UDP 8805), 490 TCP (SBI 7777), 4 ICMP. No GTP-U (udp/2152).
- **Every SCTP frame appears twice** (veth and cni0): frames 23/24, 151/152, 153/154 and 157/158.
- Frame 23: NGAP InitialUEMessage (procedureCode 15, PPID 60, dst port 38412). It carries a plain Registration request `7e 00 41`. Registration type octet 0x79 means initial registration, FOR=1, ngKSI 7. The 5GS mobile identity is a SUCI (type 1, SUPI format IMSI), PLMN `99 f9 07` = MCC 999 / MNC 70, routing indicator 0000, protection scheme 0 (null), HNPKI 0, MSIN BCD `00 00 00 00 99`. The MSIN matches the 10-digit MSISDN that the gradiant image appends after MCC+MNC.
- Frame 151: NGAP DownlinkNASTransport (procedureCode 4) carrying a plain Registration reject `7e 00 44`, **5GMM cause = 7** ("5GS services not allowed"). This matches DEVLOG ("`Registration reject [7]`", Phase 7 scenario table).
- Frames 153 and 157: NGAP UEContextRelease (procedureCode 41), Command (initiatingMessage) then Complete (successfulOutcome).
- No Authentication request (0x56) was found between frames 23 and 151. The reject comes before authentication, which fits an AUSF/UDM user-not-found result.
- PFCP Heartbeat Request/Response (types 1/2) roughly every 11 s (frames 1–8, 243–250, 329–336, 425–432, 521–528).

### BLOCKING

**TB1. E4 will fail on a healthy lab: `fivegs_smffunction_sm_pdusessioncreationfail` has no series until a PDU session fails, and the dashboard has 18 targets, not 17.**
Evidence: `phase3/manifests/dashboards/neoncore-5g.json` has 10 panels and 18 targets (1+1+1+2+1+3+2+2+4+1). Open5GS v2.8.0 `src/smf/metrics.c` defines `sm_pdusessioncreationfail` as a **by-cause** counter (label `cause`). Its instance is created lazily in `smf_metrics_inst_by_cause_add()`, so the series only exists after a failure. E4 currently demands "each of the 17 targets returns ≥ 1 series with ≥ 1 non-null value". The plan deliberately restarts SMF after UPF Ready (no failures), so on Proxmox E4 would fail, or would pass only if a failure happened.
Clause: TS 28.552 (SM.PduSessionCreationFail measurement, sub-clause not verified). The behaviour itself comes from Open5GS source, not from 3GPP.
**Fix (E4 threshold text and the B4/§1 wording):** "The dashboard has exactly the 10 panels and **18 targets** of `phase3/manifests/dashboards/neoncore-5g.json`. Each target returns ≥ 1 series with ≥ 1 non-null value, **except `fivegs_smffunction_sm_pdusessioncreationfail`**, which Open5GS creates per `cause` only on the first failure. That target must be absent or must not increase over the run window. An increase fails E4 and is reported with its `cause` label. Every panel shows data from at least one of its targets." In B4, change "17 targets" to "18 targets".

**TB2. The registration-reject cause must have an absolute expected value, not only "equal to B".**
Evidence: the scenario's runner PASS only matches the AMF log substring "Registration reject" (`phase6/scenarios.py` `registration_reject`, `phase6/runner.py` `_tail_until`), and that matches a reject for any cause. The label of the scenario is "unprovisioned IMSI → reject". `traces/rogue-ue-reject.pcap` frame 151 and DEVLOG both show #7. As written, a degraded B with a different cause (for example #111 protocol error, or #9) would make the wrong cause the pass condition on Proxmox.
Clause: TS 24.501 §9.11.3.2 (5GMM cause, Table 9.11.3.2.1: #7 = 5GS services not allowed) and §5.5.1.2.5 (initial registration not accepted by the network).
**Fix (§3 V2, registration-reject bullet):** "Registration reject (0x44) for the run UE with `nas-5gs.mm.5gmm_cause == 7` (5GS services not allowed; reference: `traces/rogue-ue-reject.pcap`, and DEVLOG). No Registration accept for that UE. The cause must also equal B's (C2). If B shows a cause other than 7, B is recorded as degraded, and Proxmox must still show 7." Also, in §1 "If B can't be captured", state that the expected cause stays 7.

**TB3. The deregistration scenario must require Deregistration accept (0x46), not leave it as [B].**
Evidence: the scenario sends `nr-cli imsi-… --exec "deregister normal"` (`phase6/ue_pod.py` `exec_deregister`), which is a UE-originating de-registration that is not switch-off. For that case the AMF must answer with DEREGISTRATION ACCEPT. The runner passes on the AMF log "Deregistration request", which only proves the request was received. With no B (the fallback pcap covers registration-reject only), the deregistration check would accept a procedure that never completed.
Clause: TS 24.501 §5.5.2.2.1/§5.5.2.2.2 (UE-initiated de-registration; the network sends DEREGISTRATION ACCEPT unless switch-off) and TS 23.502 §4.2.2.3.2.
**Fix (§3 V2, deregistration bullet):** "…then a UE-originating Deregistration request (0x45) with `nas-5gs.mm.switch_off == 0`, **followed by a Deregistration accept (0x46) on the same UE (required, not [B])**. If switch_off is 1, the pcap is invalid (the scenario did not do what its label says). [B] NGAP UEContextRelease (procedureCode 41). [B] PFCP Session Deletion (54/55), tied as in TB4."

**TB4. V2 defines the tie to the run only through `ngap.RAN_UE_NGAP_ID`, but PFCP carries no NGAP IDs, so the [B] PFCP items have no tie rule.**
Evidence: V2 says "The responses below must be on the same `ngap.RAN_UE_NGAP_ID`". PFCP 50/51/54/55 (N4) carries an SEID and a UE IP address, never an NGAP ID. Section 3 is binding, and builders cannot change it after approval, so the evaluator would have to improvise. On a lab with a background UE and leftover sessions from earlier initial-registration runs (the UE pod is deleted without deregistering), an untied PFCP message is weak evidence.
Clause: TS 29.244 §7.3 Table 7.3-1 (50/51 Session Establishment, 54/55 Session Deletion), §7.5.2 (UE IP Address IE in Create PDR), §7.2.2.4 (SEID in the header); TS 23.502 §4.3.2.2.1 (N4 session establishment in UE-requested PDU session establishment).
**Fix (append to §3 V2):** "PFCP tie rule: a PFCP Session Establishment Request (50) belongs to the run UE if a UE IP Address IE in it equals the IPv4 PDU address in that UE's PDU session establishment accept (0xc2, on the run's RAN_UE_NGAP_ID). Its Response (51) is matched by PFCP sequence number. A Session Deletion Request/Response (54/55) belongs to the run UE if its header SEID equals the F-SEID that the Establishment Request/Response pair for that UE assigned. If the PDU address can't be read from the pcap, the PFCP items are reported as 'untied' and do not count toward C2." (The evaluator confirms the exact tshark field names with `tshark -G fields` on the pinned version before the plan is frozen.)

### ADVISORY

**TA1. Codes and ports confirmed (no change needed).**
- 5GMM message types are correct: 0x41 Registration request, 0x42 accept, 0x43 complete, 0x44 reject, 0x45 Deregistration request (UE originating), 0x46 Deregistration accept (UE originating). TS 24.501 §9.7, Table 9.7.1. Note that 0x47/0x48 are the UE-terminated pair.
- 5GSM types are correct: 0xc1 PDU session establishment request, 0xc2 accept (0xc3 reject). TS 24.501 Table 9.7.2.
- PFCP types are correct: 50/51 Session Establishment, 54/55 Session Deletion (52/53 is Modification). TS 29.244 Table 7.3-1.
- Ports are correct and match the manifests:
  - NGAP: SCTP 38412, PPID 60 (TS 38.412 §7; `phase2/manifests/03-nfs.yaml` amf Service, pcap frame 23).
  - GTP-U: UDP 2152 (TS 29.281 §4.4.2).
  - PFCP: UDP 8805 (TS 29.244 §4.2.2).
- Wireshark fields `nas-5gs.mm.message_type`, `nas-5gs.sm.message_type`, `nas-5gs.mm.suci.msin`, `nas-5gs.mm.5gmm_cause`, `ngap.RAN_UE_NGAP_ID` and `pfcp.msg_type` exist (dfref).

**TA2. Pin tshark ≥ 4.2 and pre-check the field names.**
The dfref lists the `nas-5gs.*` field names only from 4.2.0 on. Older tshark (for example 3.6 on Ubuntu 22.04) uses `nas_5gs.*`, and `-Y`/`-e` with the wrong name aborts. The T0 apt candidate is 4.2.2, so the names in the plan are right for it. Suggestion: `pcap_check.py` runs `tshark -G fields` and `tshark -G defaultprefs`, and fails loudly if any field it uses or `nas-5gs.null_decipher` is missing. The plan already does this for the preference; extend it to the fields. Whether `nas-5gs.null_decipher` exists in 4.2.2 is **not verified** (tshark not installed).

**TA3. NEA0 / null_decipher wording, and a guard.**
- `amf-config` has `ciphering_order: [NEA0, NEA1, NEA2]` (`phase2/manifests/01-configmaps.yaml`), so NEA0 is selected. The preference matters for security header types 2 and 4 ("integrity protected **and ciphered**"; TS 24.501 §9.3.1), for example Registration accept/complete and Deregistration request. Messages that are only integrity protected (types 1 and 3) decode anyway. Suggested rewording: "because Open5GS selects NEA0, the integrity-protected-and-ciphered NAS messages are plaintext and can be decoded".
- Guard: check that the Security mode command (0x5d) for the run UE has `nas-5gs.mm.nas_sec_algo_enc == 0`. If it isn't 0, report "cipher not NEA0" and don't report "0x42 missing".

**TA4. Duplicate frames.**
`tcpdump -i any` on the node captures every pod-to-pod frame on both the veth and cni0 (pcap frames 23/24, 151/152). Presence checks are fine. Any counting (number of Registration requests, "exactly one reject") and any frame numbers cited as evidence should de-duplicate, for example by IP ID plus SCTP TSN, or keep the first frame only.

**TA5. Where the 5GSM messages sit.**
0xc1 sits inside UL NAS Transport (0x67). 0xc2 sits inside DL NAS Transport (0x68), carried in NGAP PDUSessionResourceSetupRequest (procedureCode 29) as `ngap.pDUSessionNAS-PDU`, **not** `ngap.NAS_PDU`. Match on `nas-5gs.sm.message_type`, not on bytes extracted from `ngap.NAS_PDU`.

**TA6. Fail on a PDU Session Establishment Reject (0xc3) for the run UE, and record the 5GSM cause.**
The DEVLOG SMF↔UPF stale-association symptom is exactly this: PDU sessions rejected with NETWORK_FAILURE. That is the most likely migration-specific signalling failure, and today initial-registration would still PASS. Clause: TS 24.501 §9.11.4.2 (5GSM cause).

**TA7. Correlation robustness.**
- Use the pair (RAN_UE_NGAP_ID, AMF_UE_NGAP_ID) once the AMF has assigned it (it appears in the first downlink message). Restrict to the single gNB SCTP association.
- RAN_UE_NGAP_ID is unique only per gNB and per gNB lifetime (TS 38.413 §9.3.3.2). A gNB restart in the window could reuse an ID.
- If the UE ever went CM-IDLE before deregistering, the Deregistration request would arrive in a new InitialUEMessage with a new RAN_UE_NGAP_ID, and it would carry the 5G-GUTI, not the SUCI (TS 24.501 §5.5.2.2.1). Allow a fallback tie through the 5G-GUTI/5G-TMSI from the Registration accept. This is not expected today: neither Open5GS nor UERANSIM triggers an inactivity release in this config (not verified live).

**TA8. Registration-reject: extra items to record.**
The reference pcap shows UEContextRelease Command/Complete (frames 153/157) after the reject, and no Authentication request before it. Suggestion: record UEContextRelease as [B] for this scenario. Also record "Authentication request present: yes/no". It should be "no", because the reject comes before authentication. That matters for Stage 7, where wrong K/OPc must show an authentication failure (0x59 or 0x58 / #20/#21) and not this pattern.

**TA9. [B] items can race the capture stop.**
- initial-registration PASSes on the AMF "Registration complete" line. The finally block then waits about 2 s (`is_healthy(settle_s=2.0)`) plus kubectl exec time before SIGINT. PDU session establishment (0xc1/0xc2, PFCP 50/51/52/53) follows Registration complete, normally within that window, but this is **not measured**.
- E3 allows a retry only for a tracer stall. Suggestion: `pcap-summary.json` records the time from 0x43 to the last frame. A missing [B] item with a gap under 2 s is then classified as "capture window", not as a protocol failure.

**TA10. Metric names and directions.**
- Use the full names in E4: `fivegs_amffunction_rm_reginitreq` / `fivegs_amffunction_rm_reginitsucc` (TS 28.552 RM.RegInitReq/RM.RegInitSucc; sub-clause not verified).
- Verified in Open5GS v2.8.0 `src/amf/gmm-sm.c` (`common_register_state`): `AMF_METR_GLOB_CTR_RM_REG_INIT_REQ` is a global counter, incremented right after `gmm_handle_registration_request()` and before AUSF/UDM. So the unprovisioned-IMSI scenario counts, and "+3 req / +2 succ per suite" is consistent. `reginitsucc` being global is **not verified**.
- N3 direction matches the patch: `INDATAPKTN3UPF` is incremented in the GTP-U receive path (uplink from the gNB), `OUTDATAPKTN3UPF` in the tun receive path (downlink to the gNB) (`phase2/upf-metrics-patch/gtp-path-metrics.patch`). So "in ≥ 20, out ≥ replies" is right. Both are global counters.

**TA11. Lazily created series need the background UE to register after every NF (re)start.**
The PCF `pa_policy*` counters are by-slice and lazy (`src/pcf/metrics.c`), and so are the SMF `sm_sessionnbr` and `pdusessioncreation{req,succ}` counters (`src/smf/metrics.c`). They only exist after the background UE registers and opens a PDU session following that NF's start. The UPF → SMF → UE order (UE last) guarantees this. Keep it on every path, including T10 after the rollback boot (see TA12).

**TA12. Start order and the T10 boot.**
- After a VM boot with the Docker runtime, pod sandboxes are recreated and pod IPs can change. The SMF stale-UPF problem (DEVLOG "SMF caches its UPF PFCP association by IP") then reappears.
- T10 step (2) says "rollback … then boot". It should say "boot, then `start.sh` (UPF → SMF → UE), then start R3/E1".
- Deploy applies 03–05 together. Also wait for AMF Ready before relying on the gNB, and verify NG Setup. The `gnb{nf="amf"} == 1` gauge in E4 already detects a missing NG Setup (TS 38.413 §8.7.1). Whether UERANSIM 3.3.0's gNB reconnects SCTP by itself after the AMF changes IP is **not verified**. If it doesn't, the recovery order should include gNB before UE.
- With D6 `on_boot` = on and workloads not scaled down, the same recovery is needed after an unplanned host reboot.

**TA13. SCTP on the 6.8 kernel.**
- `modprobe sctp` (A7) is what N2 needs. Keep the headless Services unchanged ("migrate before improving"), even though SCTP conntrack is built into `nf_conntrack` on recent kernels, unlike the missing `nf_conntrack_proto_sctp` in DEVLOG Phase 2. Don't add a `modprobe nf_conntrack_proto_sctp` to the kernel role: that module no longer exists separately, and the step would "fail loudly" on a healthy VM.
- The nftables guard only matches the LAN NIC, so N2/N3/N4 on cni0 is untouched, as the plan says.
- Open5GS UPF is a userspace tun UPF, so no `gtp5g` kernel module is needed.

**TA14. MTU and GTP overhead.**
- On a single node, N3 (gNB pod → UPF pod) stays on cni0 and never crosses the Proxmox bridge. Only decapsulated, MASQUERADEd UE traffic leaves the VM.
- The SMF advertises an MTU of 1400 to the UE (`smf-config` `mtu: 1400`). GTP-U adds about 44 bytes: IPv4 20, UDP 8, GTP 8 with optional fields 4, PDU Session Container 4 (TS 29.281 §5, TS 38.415). That gives about 1444 bytes, under flannel's cni0 MTU of 1450 when the VM NIC is 1500. UERANSIM's UE↔gNB RLS/UDP leg adds its own overhead on the same bridge (size not verified).
- Risk: an owner VLAN or bridge MTU below 1500 shrinks flannel's MTU and makes large UE packets fragment or drop. The E2 ping (84 bytes) won't show this.
- Suggestion (informational, no threshold): record the MTU of the VM NIC, `flannel.1`, `cni0` and `uesimtun0` in B5 and on Proxmox, and run one `ping -M do -s 1372 -I uesimtun0 -c 3 8.8.8.8`.

**TA15. Keep E7 scans apart from E2/E3.**
The tracer runs `tcpdump -i any` with hostNetwork, so it also sees the VM's LAN NIC. Its BPF matches `sctp`, `udp port 8805`, `udp port 2152` and `icmp`, which are exactly the E7 `-sY 38412` and `-sU 2152,8805` probes. Scans that overlap a suite would put malformed PFCP/GTP and LAN-host addresses into scenario pcaps. Schedule E7 outside the E2/E3 windows, and note in `pcap-summary.json` any frames from non-pod source addresses.

**TA16. Leftover contexts (informational).**
initial-registration deletes the UE pod without deregistering. The AMF registration and the SMF/UPF PDU session for IMSI …9901 stay until the next run re-registers the same SUCI (behaviour on re-registration not verified). Over 5 suites, record `sm_sessionnbr`/`upf_sessionnbr` before and after (no threshold). This is unchanged from WSL2, so B shows it too.

**TA17. Clause citations.**
The plan cites no 3GPP clause for any expected sequence. Suggestion: add one line to §3: "Expected sequences: TS 23.502 §4.2.2.2.2 (registration), §4.2.2.3.2 (UE-initiated deregistration), §4.3.2.2.1 (PDU session establishment); NAS codes TS 24.501 §9.7; PFCP TS 29.244 Table 7.3-1; NGAP TS 38.413 (procedure codes 15 InitialUEMessage, 4 DownlinkNASTransport, 46 UplinkNASTransport, 14 InitialContextSetup, 29 PDUSessionResourceSetup, 41 UEContextRelease, 21 NGSetup)". Procedure codes 15, 4 and 41 match the reference pcap. The other codes are **not verified** against a capture.

**TA18. UERANSIM limits.**
The plan makes no handover or periodic-TAU claim. The TUI GIF uses only `r`/`p`/`l` and `s` initial-registration. OK.

### Not verified in this review
- No tshark run on any pcap (tshark is not installed).
- Whether `nas-5gs.null_decipher` exists in tshark 4.2.2.
- Proxmox-side behaviour of anything (lab not contacted).
- PDU session timing relative to the capture stop.
- UERANSIM gNB SCTP reconnect behaviour.
- `reginitsucc` being global.
- The exact field names for PFCP UE IP / F-SEID and for the NAS PDU address.
- Spec text (clause numbers come from my own knowledge, not re-read).

## Build review (R1, 2026-11-10)

Reviewer: telco-reviewer. Object: R1 evidence in `project/reports/L0/eval/run-1-proxmox/` (README, `pcap-summary-1..5.json`, `suite-1..5.log`, `e4.json`, `ping-*.txt`, `ping-n3.json`, `ping-gtpu.json`, `t3b-fields.json`, `grafana-panels.json`, `lan/nad.json`, `versions.txt`) and all 15 local pcaps under `pcaps/`.
The lab was not contacted. There is no WSL2 baseline, so `traces/rogue-ue-reject.pcap` is the reference.

**How I checked.**
- Every pcap was read with `tshark -n -r <pcap> -o nas-5gs.null_decipher:TRUE` (TShark 4.2.2, the version in `versions.txt`), read only, unprivileged. Nothing was copied into the repo.
- I read all 15 pcaps, not a sample: NGAP procedure code, RAN_UE_NGAP_ID, NAS security header type, 5GMM/5GSM message type, registration type, identity type, SUCI MSIN, 5G-TMSI, NAS algorithms, causes, switch_off, PDU address, and PFCP type/seq/SEID/UE IP/cause. I used `-V` on single frames for NGAP causes, identities, ePCO and PFCP IEs.
- I read `evals/l0/pcap_check.py` in full.
- The Open5GS counter behaviour comes from the v2.8.0 source (`src/amf/gmm-sm.c`, fetched from the public GitHub tag).
- Clause numbers come from my own knowledge of the Rel-17 specs. I did not re-read the spec text, so the sub-clause numbers are "not verified against the document".

Frame numbers below are raw tshark frame numbers in the named pcap (first copy). Pcap names are shortened to `<scenario>-<HHMMSS>`. Every pcap is `scenario-<scenario>-<msin>-20261110-<HHMMSS>.pcap`.

### 1. Scenario procedures (15/15 pcaps read)

**initial-registration: correct in 5/5.** Reference `initial-registration-052042` (RAN_UE_NGAP_ID 3):

| Frame | Message | Notes |
|---|---|---|
| 87 | NGAP InitialUEMessage (15) + Registration request 0x41 | Plain NAS. 5GS registration type 1 = initial. Identity SUCI, MSIN 0000009901 |
| 227 | DownlinkNASTransport (4) + Authentication request 0x56 | |
| 229 | UplinkNASTransport (46) + Authentication failure 0x59 | 5GMM cause #21 (synch failure), see TA20 |
| 263 / 265 | Authentication request 0x56 / Authentication response 0x57 | |
| 299 | Security mode command 0x5d | Security header type 3, **NAS ciphering algorithm 0 = 5G-EA0 (NEA0)**, integrity algorithm 2 = 128-5G-IA2 |
| 301 | Security mode complete 0x5e | Header type 4. Carries the full Registration request in the NAS message container, with IMEISV |
| 497 / 499 | InitialContextSetup (14) Request with Registration accept 0x42 / Response | 0x42 has header type 2 and carries a 5G-GUTI |
| 503 | Registration complete 0x43 and UL NAS Transport 0x67 with PDU session establishment request 0xc1 | Two UplinkNASTransport chunks in one SCTP packet |
| 505 | Configuration update command 0x54 | NITZ, sent by Open5GS after Registration complete |
| 711 / 713 | PFCP Session Establishment Request 50 / Response 51 | 50: UE IP 10.45.0.3, CP F-SEID 0x63. 51: header SEID 0x63, cause 1 = Request accepted, UP F-SEID 0xbb2 |
| 755 / 765 | PDUSessionResourceSetup (29) Request with DL NAS Transport 0x68 and PDU session establishment accept 0xc2 / Response | 0xc2: PDU address 10.45.0.3, PSI 1, IPv4, SSC mode 1, SST 1, DNN internet |
| 773 / 775 | PFCP Session Modification Request 52 / Response 53 | Header SEIDs 0xbb2 / 0x63, cause 1 |

No 0xc3 and no 5GSM cause appeared in any pcap. Suites 2–5 (`-052157` RAN 7, `-052252` RAN 11, `-052347` RAN 14, `-052444` RAN 18) show the same sequence with UE IPs 10.45.0.5, .8, .10 and .12.
Clauses: TS 23.502 §4.2.2.2.2 (registration), §4.3.2.2.1 (UE-requested PDU session establishment, including N4 establishment and the N4 modification that carries the AN tunnel info), §4.2.4.2 (UE configuration update); TS 24.501 §5.5.1.2, §5.4.1.3, §5.4.2, §6.4.1; TS 29.244 Table 7.3-1.

**registration-reject: correct in 5/5. Cause #7 in 5/5, and authentication is absent before the reject in 5/5, as in the reference pcap.** Reference `registration-reject-052100` (RAN 4):

| Frame | Message | Notes |
|---|---|---|
| 9 | InitialUEMessage + Registration request 0x41 | SUCI, MSIN 0000009902, initial |
| 49 | DownlinkNASTransport + Registration reject 0x44 | Security header type 0 (plain), **5GMM cause 7** |
| 51 / 55 | UEContextRelease (41) Command / Complete | |

No 0x56, 0x5d or 0x42 is present. The other four are the same (`-052210` frames 1/41/43/47, `-052304` 31/71/73/77, `-052400` 1/41/43/47, `-052458` 1/41/43/47).
This is the same pattern as `traces/rogue-ue-reject.pcap` frames 23/151/153/157.
Clauses: TS 24.501 §5.5.1.2.5 and §9.11.3.2 (#7 = 5GS services not allowed). A plain reject before security is allowed by TS 24.501 §4.4.4.2.

**deregistration: correct in 5/5.** Reference `deregistration-052112` (RAN 5):
- Frames 25–339: the same registration, authentication and PDU session sequence as above. UE IP 10.45.0.4.
- Frame 437: Deregistration request (UE originating) 0x45, header type 2, **switch_off = 0**.
- Frames 445 / 447: PFCP Session Deletion Request 54 (header SEID 0xc69 = the UP F-SEID from 51) / Response 55 (header SEID 0xed2 = the CP F-SEID from 50, cause 1).
- Frame 525: Deregistration accept (UE originating) 0x46.
- Frames 527 / 531: UEContextRelease Command (Cause nas = 2, deregister) / Complete.

The order is N4 release, then NAS accept, then N2 release. That matches TS 23.502 §4.2.2.3.2 and TS 24.501 §5.5.2.2.1–2. The other four suites are the same (RAN 9, 13, 16, 20; switch_off 0 in each).

**NGAP procedure codes, all frames of all 15 pcaps:** 4 ×57, 14 ×26, 15 ×18, 29 ×22, 41 ×22, 46 ×65.
- 4 DownlinkNASTransport, 14 InitialContextSetup, 15 InitialUEMessage, 29 PDUSessionResourceSetup, 41 UEContextRelease and 46 UplinkNASTransport all match their tshark decode names. This confirms the codes that TA17 left unverified (TS 38.413 §9.4.7).
- 21 NGSetup is not in any scenario pcap (it happened before the window), so it is still not verified against a capture.

**TA3 confirmed: NEA0 was selected in all 13 Security mode commands** (10 SUCI registrations and 3 GUTI re-registrations). Integrity is 128-5G-IA2 in every one; NIA0 is never used.

### 2. What `pcap_check.py` accepted

**No false PASS found.** I checked each rule against the pcaps:
- **V2 tie.** The run UE is identified by the RAN_UE_NGAP_ID of the 0x41 that carries the suite MSIN. In every pcap this picks exactly the RAN ID I found by hand.
- **Required items.** The required items (0x41/0x42/0x43; 0x41/0x44 with #7; 0x45 with switch_off 0, then 0x46) are present on that ID in every pcap.
- **switch_off parsing.** tshark prints `False`, and `to_bool_int` maps it to 0, which is correct.
- **TB4 PFCP tie.** 50 is matched by UE IP and 51 by seq. 54/55 are matched by their header SEID against the F-SEIDs collected from 50/51. For 54 the header SEID is the UP F-SEID from 51; for 55 it is the CP F-SEID from 50. This is the correct direction logic (TS 29.244 §7.2.2.4.2). The set holds both SEIDs, so it would also accept a reversed SEID. That is harmless here.
- **TA4 duplicates.** `dedup` removes exactly half the frames in every pcap.

**The RAN_UE_NGAP_ID 6 registration in `deregistration-052112` is the scenario UE re-registering by itself. It is not the background `ue` pod, and it is not a runner artifact.**
- Frame 545 is an InitialUEMessage on RAN 6, 204 ms after the UEContextRelease of RAN 5. It carries a Registration request (type 1 = initial) identified by **5G-GUTI with 5G-TMSI 0xc000058f**.
- That is exactly the 5G-TMSI the AMF assigned to the run UE in the Registration accept of frame 237 (RAN 5).
- The background UE never received that GUTI. The IMEISV (4370816125816151) is the same, but it also appears in the initial-registration pcap, so it is a shared default and does not distinguish UEs.
- So, after the UE-initiated non-switch-off de-registration, UERANSIM's UE immediately starts a new initial registration with its stored 5G-GUTI. TS 24.501 §5.5.2.2.2 allows a UE that is not switched off to register again.
- The runner did not trigger it. It is captured only because the runner keeps the pod and the capture alive for about 2 s after the PASS line (TA9).

The same thing happens in 3 of 5 deregistration pcaps:
- `-052112`, RAN 6: authentication without resync (585/587), SMC NEA0 (621), Registration accept with a new 5G-TMSI 0xc000044e (721). Then, at frame 727, the UE sends **5GMM STATUS 0x64 with cause #101** ("message not compatible with the protocol state") instead of Registration complete.
- `-052221`, RAN 10: the registration completes (727: 0x43 + 0xc1), and a **new PDU session** is established: PFCP 50/51 at 811/813 for 10.45.0.7, 0xc2 at 823, 52/53 at 839/841.
- `-052411`, RAN 17: the same as RAN 6. The Registration accept is at 721 (05:24:18.228Z) and 5GMM STATUS #101 at 727. The AMF then releases RAN 17 with UEContextRelease Command, Cause nas = normal-release (`initial-registration-052444` frames 405/407, 05:24:48.240Z), **30.01 s after the accept**. That fits T3550 (6 s) expiring 5 times and the AMF aborting the procedure (TS 24.501 §5.5.1.2.8 and Table 10.2.2). This is inferred from timing only; I did not see the AMF log or the retransmissions.
- In suite 3 there is no re-registration at all: RAN 14 starts suite 4. After suite 5 none is visible, and the E4 counters fit "none" (point 3).
- I did not determine why UERANSIM answers #101 in 2 of the 3 cases.

**Did `pcap_check` credit anything wrongly because of it? No.** None of RAN 6/10/17 carries a SUCI, so none is in `run_ran_ue_ngap_ids` (the summaries show `["5"]`, `["9"]`, `["16"]`).
- The RAN 10 PFCP 50/51 for 10.45.0.7 is not used for the tie: `pdu_addrs` holds only 10.45.0.6, from RAN 9.
- The RAN 17 UEContextRelease in `initial-registration-052444` is not credited to RAN 18 (its `items` have no `ngap:41`).

What the checker does **not** do (findings TA21, TA22 and TB7 below):
- It does not report the run UE's second NG connection.
- It does not report a 5GMM STATUS, or the #21 resync.
- Its background-UE exclusion was **never exercised**. The background `ue` pod sent no N2 signalling in any of the 15 pcaps: the only RAN IDs seen are 3–20, all scenario UEs or their re-registrations.

**Duplicate frames (TA4), corrected detail.**
- Each pod-to-pod frame appears on two different ifindexes. For gNB↔AMF SCTP these are 24 and 21; for SMF↔UPF PFCP, 42 and 23; for SBI TCP, 21 and 14. The two copies are 5–30 µs apart, well inside `DUP_WINDOW_S` = 0.05 s.
- tshark 4.2.2 marks the second SCTP copy "DATA (retransmission)" and does **not** dissect NGAP/NAS in it (`initial-registration-052042` frame 88 is the copy of 87, and 228 of 227). So NGAP/NAS counts would not be doubled even without dedup.
- PFCP and TCP copies are fully dissected in both copies, so dedup is needed for them, and it works.
- My plan-review wording "veth and cni0" was a guess. Which interface each ifindex maps to is not verified, because SLL2 carries only the ifindex.

### 3. Counters (E4: `reginitreq` +18, `reginitsucc` +11)

**Consistent, but only once the 3 automatic GUTI re-registrations are counted. The background UE contributes 0.**
- Open5GS v2.8.0 `src/amf/gmm-sm.c` line 1685 (`common_register_state`) increments `RM_REG_INIT_REQ` for every Registration request of type initial, before AUSF/UDM. So rejects count.
- Line 3228 (in `gmm_state_initial_context_setup`) increments `RM_REG_INIT_SUCC` **on Registration complete**, not on Registration accept. This settles the "not verified" item TA10.
- **`reginitreq` +18:** the pcaps contain 18 InitialUEMessages (procedureCode 15), with RAN IDs 3–20 contiguous, and each carries a type-1 (initial) Registration request. That is 15 scenario registrations (5 × initial-registration, reject and deregistration) plus 3 GUTI re-registrations (RAN 6, 10, 17).
- **`reginitsucc` +11:** 10 Registration completes (5 × initial-registration + 5 × deregistration) plus 1 (RAN 10). RAN 6 and 17 sent 5GMM STATUS instead of 0x43, so they are not counted.
- **Background UE:** E1 shows a restart delta of 0, and no pcap has an N2 message from it. Its registration predates the window. A periodic registration update would not touch these counters (they are initial-type only).
- The deregistration itself does not change either counter.
- The E4 thresholds (≥ 3 / ≥ 2 per suite) are robust to this. But the README's figures can only be explained by counting the re-registrations (TB7).

### 4. N3 and the tracer

- **N3 counters are consistent with one GTP-U G-PDU per ICMP packet each way.**
  - `ping-n3.json`: in and out rise by exactly +20 per run (120 → 140 → 160 for runs 1–2), with 20/20 replies each (`ping-1..3.txt`).
  - In the patch, `INDATAPKTN3UPF` counts GTP-U received from the gNB (uplink echo requests) and `OUTDATAPKTN3UPF` counts GTP-U sent to the gNB (downlink replies).
  - The 84-byte packets do not fragment.
  - These counters are the UPF's own counts, not wire evidence.
- **`ping-gtpu.json` is not a measurement.** All 3 windows read `neoncore-20261110-044839.pcap` with the same sha256. That file was last written at 04:53:42Z, before the E2 windows (from 05:17Z). Yet the JSON says `"status": "tested"` with 0 frames (TB5).
- **Evidence that would show GTP-U:**
  - What to capture: a capture on the node that covers the E2 window, filter `udp port 2152`.
  - What it should show: GTP-U G-PDUs (message type 0xff) between the gNB pod IP and the UPF pod IP. After dedup, 20 uplink and 20 downlink:
    - uplink: gNB → UPF, inner ICMP echo request 10.45.0.2 → 8.8.8.8;
    - downlink: UPF → gNB, inner echo reply.
  - Each G-PDU should carry a PDU Session Container extension header with the QFI (TS 29.281 §5.1–5.2, TS 38.415).
  - How to tie it to the background UE:
    - First choice: by inner IP 10.45.0.2.
    - Better: by TEID. The UL TEID is the UPF's F-TEID (from PFCP 51 Created PDR, or the NGAP PDUSessionResourceSetupRequest UL NG-U TNL info), and the DL TEID is the gNB's (from the Setup Response / PFCP 52). The background UE's session predates the window, so the TEID tie needs its establishment pcap.
  - A source that works without restarting the tracer: a scoped second tcpdump in the tracer pod during E2, as `phase6/capture.py` does for scenarios.
- **Must R2 include it?** Under the frozen plan, the E2 GTP-U item is [B]: reported, not required without B. So R2 can pass without it. Making it required needs a plan amendment, which is the lead's and owner's decision.
  - My recommendation is to include it. It is the only wire-level proof that user plane runs over N3 as GTP-U on Proxmox. Stage 7 will rely on the continuous tracer, which stalled here for unknown reasons.
  - What R2 must do in any case: record the tracer's state (last write time of its current file) before E2, and label GTP-U "not tested: tracer stalled" when the file is stale (TB5).

### 5. Multus

**Nothing in the 5G core design needs a Multus attachment.**
- `phase2/manifests/01-configmaps.yaml` binds every NF, including UPF PFCP (N4) and GTP-U (N3) at lines 276–281, to `dev: eth0`. That is the pod's default flannel interface.
- N6 is the UPF's `ogstun` (10.45.0.1/16) with `iptables -t nat ... -o eth0 -j MASQUERADE` (`phase2/manifests/03-nfs.yaml` lines 321–331).
- No manifest in phase2–4 or phase6 has a `k8s.v1.cni.cncf.io/networks` annotation, a NetworkAttachmentDefinition, or a macvlan/ipvlan reference. `lan/nad.json` confirms that every pod has only `cbr0 on eth0`.
- DEVLOG Phase 1 used Multus only for a one-off macvlan test NAD (`phase1/test-macvlan-nad.yaml`, "applied and torn down"). The 5G core never used it.
- That test working on WSL2 implies the NAD CRD existed there. Its absence on Proxmox most likely comes from the unpinned `rke2-multus` chart (plan line 438); this is not verified.
- 3GPP does not require separate interfaces per reference point (TS 23.501 §4.2, where reference points are logical).
- See TA23 for the remaining doc point.

### 6. MTU (TA14)

**Not recorded anywhere in R1.**
- `versions.txt` has no MTU line. No R1 file has an MTU value; "mtu" appears in the run directory only in the ping headers.
- No `ping -M do -s 1372` was run.
- Plan §8.6 and B5 (amended per TA14) ask for these values. `evals/l0/capture_baseline.sh` lines 75–82 already has the commands, but they were only written for B, and B was waived.
- **New pcap fact:** the PDU session establishment accept does **not** signal an MTU to the UE.
  - The ePCO in 0xc2 (`initial-registration-052042` frame 755) contains only two DNS Server IPv4 Address containers (0x000d). There is no IPv4 Link MTU container (0x0010; TS 24.501 §9.11.4.6, TS 24.008 §10.5.6.3).
  - So SMF `mtu: 1400` (`01-configmaps.yaml` line 189) does not reach the UE, and `uesimtun0`'s MTU is whatever UERANSIM sets locally (value not verified).
- GTP extension-header presence, and so whether the overhead is 36 or 44 bytes, is not verified, because no GTP-U was captured.
- See TB6 for what R2 must record.

### BLOCKING

**TB5. `ping-gtpu.json` reports a stale file as "tested, 0 frames".**
Evidence:
- `ping-gtpu.json` runs 1–3 have `"status": "tested"` and `gtp_icmp_frames: 0` on `neoncore-20261110-044839.pcap`, with the same sha256 in all 3.
- The README says this file was last written at 04:53:42Z, before every E2 window.

Rule: "Anything not run is 'not tested'." Nothing was measured in those windows. Clause: TS 29.281 §5 (what the item would have shown).
**Fix:**
- R1: set `status` to `"not tested: tracer pcap stale (last write 04:53:42Z, before window)"` in `ping-gtpu.json`, and in the README E2 row write "[B] GTP-U: not tested (tracer stalled)" instead of "0 frames".
- R2: `ping_check.sh` checks before each run that the tracer's current file was written within the last 30 s, and uses the same label when it was not.
- Optional plan amendment (lead/owner): make GTP-U required in R2, from a scoped capture during E2.

**TB6. MTU and the path-MTU ping are required by plan §8.6/B5 but are missing from R1.**
Evidence: `versions.txt` has no MTU line, and no file records `ping -M do`. The PDU session accept carries no IPv4 Link MTU (`initial-registration-052042` frame 755). Clauses: TS 24.501 §9.11.4.6 (ePCO); TS 29.281 §5 and TS 38.415 (GTP-U overhead).
**Fix (R2 must record in `versions.txt`, informational, no threshold):**
- MTU of the VM NIC, `flannel.1`, `cni0`, `eth0` in the gnb, upf and ue pods, `ogstun` in the UPF pod, and `uesimtun0` in the `ue` pod.
- The Proxmox bridge (`vmbr*`) MTU and any VLAN tag, from lab-ops or the owner on the host (not through the lab VM).
- `kubectl -n neoncore exec deploy/ue -- ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8`, with the loss line.
- If `uesimtun0` is not 1400, record that the SMF value is not conveyed, citing the ePCO finding above.
- If L0 closes without R2, this stays "not tested" and TA14 stays open.

**TB7. R1 does not report abnormal signalling that its pcaps contain, and its E4 counter figures need it to add up.**
Evidence:
- The run UE re-registers on its own with its 5G-GUTI after every observed deregistration: `-052112` RAN 6, `-052221` RAN 10, `-052411` RAN 17 (same 5G-TMSI as the run UE's accept).
- 5GMM STATUS #101 at `-052112` frame 727 and `-052411` frame 727.
- An AMF release 30.01 s later (`initial-registration-052444` frames 405/407).
- A new PDU session 10.45.0.7 for a subscriber that the runner then deprovisions (`-052221` frames 811–841).
- Authentication failure #21 before every SUCI registration (TA20).
- The README states E3 and E4 without any of this. `reginitreq` +18 and `reginitsucc` +11 are only explained by RAN 6/10/17 (point 3).

Clauses: TS 24.501 §5.5.2.2.2 (UE re-registration after non-switch-off de-registration), §9.11.3.2 (#101, #21), §5.5.1.2.8 / §10.2 (T3550); TS 23.502 §4.2.2.3.2.
**Fix:**
- (a) README "Observations": add one entry with the above facts and frame numbers, and the E4 decomposition "18 = 15 scenario + 3 GUTI re-registrations (RAN 6, 10, 17), background UE 0; 11 = 10 + 1 (RAN 10; RAN 6/17 sent 5GMM STATUS #101 instead of Registration complete)".
- (b) `pcap_check.py`, report-only (it does not change V0–V3): add `other_ue_ngap_ids`, with identity type and 5G-TMSI for 0x41s without the run MSIN; `run_ue_guti_reregistration: true/false`, a 5G-TMSI match against the run UE's 0x42; `5gmm_status_causes`; and `auth_failure_causes`, for the run UE and for others. This needs the 5G-TMSI field name confirmed with `tshark -G fields`. `nas-5gs.mm.5g_tmsi` is **not** a valid name in 4.2.2.
- (c) R2 reports the same.

None of these three changes a pass/fail threshold, so R1's E2/E3/E4 PASS stands. They are blocking for close because the evidence must say what happened.

### ADVISORY

**TA19. Scenario procedures confirmed (point 1).** No change needed.

**TA20. Authentication failure #21 (synch failure) before every SUCI registration: 10/10.**
- First SUCI attempts: frames 229/67/57 and so on. The GUTI re-registrations (0/3) do not have it.
- `phase6/provisioning.py` builds the subscriber `security` object with `k`, `opc` and `amf` only (no `sqn`). This is a hypothesis for the cause, not verified.
- It is harmless for L0 (the resync succeeds; TS 33.501 §6.1.3.3; TS 24.501 §5.4.1.3.5).
- For Stage 7: a healthy pcap already contains an Authentication failure. A wrong-K/OPc fault label must therefore require **#20 MAC failure** (or the AUSF result), not "any 0x59".
- WSL2 parity: not verified (no baseline).

**TA21. pcap_check gaps (report-only additions; no V-rule change).**
- The TA3 NEA0 guard is not implemented. R1 is fine (13/13 NEA0).
- TA8 "auth absent before reject" is not checked. R1 is fine (0 auth in 5/5).
- PFCP 52/53 is not tracked. 52/53 carries the gNB's DL F-TEID, without which DL N3 fails (TS 23.502 §4.3.2.2.1 steps 16a–b). Suggest [B] `pfcp:52/53` for initial-registration.
- Order 0x42 < 0x43 is not checked.
- `pfcp_tie` says "untied" for the suite-1 reject pcap, which has only PFCP heartbeats. "n/a" would be clearer for a scenario with no PFCP items.

**TA22. The background-UE exclusion is untested.**
- The background `ue` pod sent no N2 traffic in any scenario pcap.
- The tie did correctly exclude a same-SUPI, GUTI-identified connection (RAN 6/10/17). But it has never been tested against another SUCI UE.
- A cheap test: a synthetic two-UE pcap in `evals/l0` tests, if the evaluator has one.

**TA23. Multus (point 5).**
- No design dependency.
- The NAD CRD absence is a Phase 1 regression of the DEVLOG success criterion "macvlan/ipvlan interfaces can be created", not of the 5G core.
- If any later stage wants separate N3/N6 networks, pin the `rke2-multus` chart version and check the CRD first.
- DEVLOG line 13 lists "Multus CNI" in the stack. A docs note "installed, unused by the core" would avoid an over-claim.

**TA24. Leftover state.**
- Initial-registration pcaps never contain PFCP 54, so the 9901 sessions are not released inside the captures.
- But `fivegs_smffunction_sm_sessionnbr` is 1 at both the start and the end of the window (`grafana-panels.json`), so the SMF does not accumulate them. Where they are released is not verified: SMF PFCP sequence gaps between captures (198–201, 212–215) are consistent with releases, but were not observed.
- `fivegs_upffunction_upf_sessionnbr` is 2 at the start and the end, against the SMF's 1. So one UPF session has no SMF context, before and after the run.
- Not a threshold. Record both gauges in R2 and note the mismatch next to the DEVLOG stale-association history.

**TA25. `capture_healthy=False` in 3 of 5 reject runs.**
- For example, `suite-1.log`: "capture file not growing (6738 -> 6738 bytes)".
- This is the runner's growth heuristic on a pcap that is complete after 4 NGAP messages. The pcap is valid (V0–V2 pass), so the flag is noise for this scenario.
- Not a PASS issue. Worth a note so Stage 7 doesn't treat it as a capture fault.

**TA26. UERANSIM limits.**
- R1 makes no handover or periodic-registration claim. OK.
- The auto re-registration and the #101 behaviour (TB7) are UERANSIM 3.3.0 UE behaviour. Any Stage 7 deregistration fault scenario must expect them.

### Not verified in this build review
- Why the UERANSIM UE sends 5GMM STATUS #101 instead of Registration complete on 2 of 3 GUTI re-registrations.
- The T3550 retransmissions themselves (outside the captures). The 30 s abort is inferred from timing.
- The root cause of the #21 resync (the missing `sqn` in the subscriber document is a hypothesis), and whether WSL2 showed it.
- Which interface name each SLL2 ifindex is (veth or cni0).
- NGSetup (procedureCode 21), which is in no scenario pcap.
- GTP-U on N3: TEIDs, PDU Session Container, overhead (no GTP-U frame in any R1 pcap).
- The `uesimtun0` MTU and all node and bridge MTUs.
- What happened in the PFCP sequence gaps between captures. Which UPF session has no SMF context.
- Why the tracer stalled.
- Whether the NAD CRD existed on WSL2 at migration time (it is implied by DEVLOG Phase 1, but not checked).
- Spec text: clause numbers are from my own knowledge, not re-read.

## Build review: first blog post (T13, `0e5d45d`, 2026-11-11)

Scope: `site/src/pages/blog/proxmox-migration.md` (94 lines) and the GIF caption at line 21. Sources: DEVLOG Stage L0 (`DEVLOG.md:627-845`), the earlier tracer note (`DEVLOG.md:481-510`), `project/notes/L0.md`, the README of every run under `project/reports/L0/eval/`, `fromzero-2/timing.json`, and the local pcaps of R1, R2, R2b, R2c and R3 read with tshark 4.2.2 (`-o nas-5gs.null_decipher:TRUE`, read-only). Product files were not changed.

### Checked against captures (tshark, this review)
- Registration reject cause #7: R1 5/5, R2 5/5, R2b 5/5, R2c 5/5, R3 3/3. In R2c, for example, `registration-reject-...-213614` frame 11 is a Registration request (0x41) with SUCI (type_id 1), and frame 51 is the Registration reject (0x44) with cause 7. There is no authentication before it. This matches post line 71.
- Authentication failure #21 (0x59): R1 10, R2 10, R2b 10, R2c 10, R3 6. No other 0x59 cause appears. The flow is Authentication request, failure #21, a second request, then the response. For example, R2c `deregistration-...-213625` frames 61, 63, 97 and 99. This matches post line 89 apart from TN1 below.
- Deregistration in R2c, 5/5: 0x45 with Switch off = Normal de-registration, then 0x46. For example, `...-213625` frames 383 and 471.
- GUTI re-registration in R2c, 5/5: InitialUEMessage with type_id 2 (5G-GUTI) at 203.3, 203.7, 205.4, 205.5 and 206.3 ms after the first UEContextRelease Command (`...-213625` frame 491, and so on). There is no #21 on these. This matches "about 200 ms" (line 88).
- 5GMM STATUS (0x64) count: R1 2, R2 1, R2b 1, R2c 0, R3 1. The post does not cite this.
- Wilson 95% lower bounds: 15/15 gives 15/(15+1.96²) = 0.796, and 9/9 gives 0.701. Lines 59 and 63 are correct.

### Checked against READMEs and notes, correct as written
Line 13: 4 cores, 8192 MiB and 40 GiB (`infra/terraform/main.tf:38,44,58`), and K3s pin. Line 14: subcommands (`infra/lab.sh:374-380`). Line 34: about 50 404s, `archive.debian.org`, v2.8.0. Line 42: stall 2 description, 2/2 repro, 4/4 cycles, 3 rotations, 0 restarts, mechanism not known. Lines 46-49. Lines 59-63: every run row matches its README (2724.4 s, 20/20 x3, R2 E1 and E6(a) 2 hits, R2b 25 < 26, R2c 25 samples and 1501.5 s, R3 1021.2 s, 9/9). Line 69: 396 s, 19:16:48Z-19:23:24Z, 1/0/0, ok=41/17 and ok=17/7, 342 s, 0-change rerun. Line 70: R2c p50 5.06-5.26 ms and p95 6.05-11.4 ms, N3 +20/+20. Line 71: suites 41-43 s. Line 72: 10/18/17 and 6/6. Line 73: {22, 6443, 30030, 30090}, 65531 filtered, laptop 0/65535, R3 scan 2. Line 74: values match R2c `mtu.txt` and the README. Line 76. Line 80.

### BLOCKING
- **TP1, line 38, "It never stalled on WSL2."** This is false as written. `DEVLOG.md:481-500` records a WSL2-era tracer stall: `tcpdump` was PID 1, Running, with no restarts, and wrote nothing for 45+ minutes. Its root cause was not isolated. `DEVLOG.md:731-732` says only that *stall 1* never happened on WSL2. Fix: "Neither of these two stalls happened on WSL2. An earlier, unexplained WSL2 stall is in DEVLOG."
- **TP2, lines 36 and 40, "twice, for two different reasons" / "Stall 1: AppArmor".** This claims more than the evidence shows. DEVLOG confirms AppArmor only for the failed `gzip` exec ("Cause (confirmed for the exec failure)", `DEVLOG.md:737`). It says "The spin itself was not explained by any denial; see stall 2" (`:750`) and "The earlier `-z` failure had the same shape: a child of PID 1 exiting" (`:765`). The triggers differ, but the stall (PID 1 at 100% in state R, no writes) may be the same unexplained effect both times. Fix: say "two different triggers", and add that AppArmor explains the denied `gzip` exec, not the spin that followed.
- **TP3, line 42, "The first full evaluator run on the VM failed on a tracer restart."** This contradicts the post's own table (line 59). R1 was the first full run on the Proxmox VM, and it passed (`run-1-proxmox/README.md`). The run that failed was R2, the first run after the from-zero rebuild (`run-2-fromzero/README.md`). Fix: "The first evaluator run after the from-zero rebuild (R2) failed ...".
- **TP4, line 81, "Only model readers were used."** I found no E9 reader evidence. There is no `readme30s/` folder under `project/reports/L0/eval/`, and `project/STATUS.md` still lists "E9 reader test" as remaining. D15 chose model readers only (`project/notes/L0.md:17`), but they have not run yet. Fix: "Reader test (E9): not run when this was written. The plan uses model readers only, so a human reader test is not tested." Update the line once E9 has run.

### Non-blocking
- **TN1, line 89, "before every SUCI registration".** The reject UE also registers with SUCI and is rejected (#7) before any authentication (see the R2c reject frames above). Precise wording: "before every SUCI registration that reaches authentication (10 per 5-suite run, 6 in R3)". The cause value and its name are right: #21 is "Synch failure" (TS 24.501 §9.11.3.2 and Annex A). The UE sends AUTS and the home network resynchronises SQN (TS 33.501 §6.1.3.3). For Stage 7: a wrong K/OPc makes the UE reject with #20 "MAC failure" (TS 24.501 §5.4.1.3.7, authentication not accepted by the UE), so a "wrong key" label must require #20, not any 0x59. "harmless" is fine for the effect (the registration succeeds), but the cause is still unverified, as the post says.
- **TN2, line 88.** The counts are selective. R2 4/5 and R2b 5/5 are left out (`DEVLOG.md:821`), while line 89 lists all runs. Also, credit the behaviour to the UERANSIM 3.3.0 UE, not to the procedure. After a UE-originating, non-switch-off de-registration, TS 24.501 §5.5.2.2 puts the UE in 5GMM-DEREGISTERED and does not require it to re-register. New fact for Stage 7: in R2c, all 5 re-registered UEs also set up a PDU session (0xc2: `...-213625` frame 789, `...-213727` 789, `...-213819` 811, `...-213911` 801, `...-214003` 779). In R1 this happened once (O-2). The R2c README does not report it.
- **TN3, line 40, "allows exec of `/bin/gzip` only".** The profile allows `/{usr/,}bin/gzip` and `/{usr/,}bin/bzip2` (`DEVLOG.md:739-740`).
- **TN4, line 30, "15m12s (911 s for the whole apply)".** 15m12s is 912 s, so the part is longer than the whole. The sources differ: 15m12s is the provider's "creation" message, and 911 s is the wall time 03:43:53Z-03:59:04Z (`project/notes/L0.md:79`). Name the sources, or write "about 15 minutes".
- **TN5, line 59, R1 row.** The row leaves out that the tracer's main capture was stalled for the whole of R1 (stall 1), so R1's GTP-U item is "not tested" (`run-1-proxmox/README.md`, E-1 and E-2). E1 passed because the pod stayed Running with 0 restarts. Suggest adding "tracer capture stalled (stall 1); GTP-U not tested".
- **TN6, line 74, MTU.** The numbers are correct. For context: 1372 + 8 (ICMP) + 20 (IP) = 1400 bytes, the `uesimtun0` MTU. The DF bit is set on the inner packet only. Whether the outer GTP-U packet on N3 was fragmented was not checked, because the tracer pcaps are on the VM. That should read "not tested". Also not measured: the Proxmox bridge (1500 is owner-supplied) and the node MTUs after the rollback. `flannel.1` and `cni0` are 1450 (lab-ops, R2c VM).
- **TN7, line 83.** "1 to 2 each" matches the three observed starts. The R3 boot also restarted `gnb` once (`run-3-restore/README.md`, "Boot restarts"), and the post leaves that out.
- **TN8, line 75.** The 1 s rollback time was supplied by the owner from the Proxmox task log. The evaluator did not measure it (`run-3-restore/README.md`, "not measured by the evaluator"). Suggest "owner-supplied".
- **TN9, line 71.** Optional: name cause 7 ("5GS services not allowed", TS 24.501 Annex A).
- **TN10, line 21, GIF caption.** The key list matches `docs/media/tui-demo.tape` (r, p, l, s, then Tab 5 to Initial Reg). The text output shows `initial-registration`, a synthetic IMSI in test PLMN 999-70, and `[result] PASS` (`docs/media/tui-demo.txt:1044-1056`). Two corrections. `p` is "UE Ping Test" (`phase5/neoncore_cli/app.py:103`): it sends user-plane traffic, so it is not a "read-only view". Suggest "r and l (views), p (UE ping)". `s` also creates a scenario UE pod (`tui-demo.txt:1053`), and the caption's "run" covers that. Outside telco scope: the site uses 3 colours that are not in `neoncore.tcss` (#16301a, #6f8a74, #c9f5c0), so "colors come from the TUI's stylesheet" is only partly true. `README.md:3` has alt text only and no caption to check.
- **TN11, lines 78-84, "What was not tested".** Also missing: E6(c)/R4, the Proxmox bridge MTU (not measured), and the outer GTP-U size (TN6).
- Aside (DEVLOG, not the post): `DEVLOG.md:829` says one 5GMM STATUS #101 appeared in each of R2, R2b and R3, but R1 had 2 (R1 O-1, RAN 6 and 17).

### Not verified in this post review
- Anything in the tracer's own pcaps, which stay on the VM: GTP-U counts and outer frame sizes.
- The AppArmor profile text and the 15 kernel-log denials (DEVLOG only). The 2/2 and 4/4 repro counts (notes only).
- The Ansible counts and the 342 s value (checked against the README and `timing.json`, not against the raw `lab-up.log`). The rollback time (owner-supplied).
- The rendered page (no build or browser run here).
- Spec text: the clause numbers above (TS 24.501 §5.4.1.3.7, §5.5.2.2, §9.11.3.2, Annex A; TS 33.501 §6.1.3.3) are from memory and were not re-read in this review.

## Final build review (L0 close)

Reviewer: telco-reviewer. Date: 2026-11-11. Branch `stage/L0`, HEAD `0f24789`. Scope: `site/src/pages/blog/proxmox-migration.md` (after `100fd30` and `8b47153`), `DEVLOG.md` (after `24fbf52`), `project/reports/L0/eval/summary.md` (identical to `project/notes/L0-eval-summary-draft.md`, checked with `diff`), the run READMEs, `readme30s/score.json`, `readme30s/run2/score.json`, `readme30s/run2/preregistration.md`, and `project/notes/L0.md` for the tracer notes. Pcaps were read with tshark 4.2.2 (`-o nas-5gs.null_decipher:TRUE`), read only, unprivileged: all R1, R2, R2b, R2c, R3 and R3 pre-rollback scenario pcaps for 5GMM STATUS, plus R2c and R3 for the counter breakdown. The lab was not contacted. No product file was changed.

### 1. Earlier BLOCKING points: all fixed
- **TB5 fixed.** `run-1-proxmox/ping-gtpu.json`: runs 1-3 say `not tested: tracer pcap stale (last write 04:53:42Z, before window)`. README E2 row (`run-1-proxmox/README.md:29`) and erratum E-1/E-2 (`:62-63`) match. R2c, R3 and pre-rollback have `tracer_max_age_s: 30` and `status: tested`.
- **TB6 fixed for R2c**, as I found in the post review (R2c `mtu.txt`). R1 MTU stays "not tested" (`summary.md:92`). That is correct.
- **TB7 fixed.** `run-1-proxmox/README.md:42-56` (O-1 to O-4, erratum E-3) has the re-registrations, both #101 frames, the 30.01 s release, the leftover PDU session, #21 10/10 and the 18 = 15 + 3 / 11 = 10 + 1 breakdown.
- **TP1 fixed** (post line 38: neither stall happened on WSL2, and the earlier unexplained WSL2 stall is named).
- **TP2 fixed** (line 36 says "two different triggers"; line 40: "AppArmor explains the denied `gzip` exec. It does not explain the spin").
- **TP3 fixed** (line 42: R2 was the first run after the from-zero rebuild; R1 passed).
- **TP4 fixed** (line 81: E9 ran, FAIL on the strict reading in both attempts, human reader not tested).
- **TN1-TN11 fixed in the post:** line 97 (#21 only on SUCI registrations that reach authentication), line 96 (all runs listed, credited to the UERANSIM 3.3.0 UE, R2c 5/5 PDU sessions), line 40 (all four profile paths), line 30 (two sources named), line 59 (R1 tracer stalled, GTP-U not tested), line 74 (inner packet only; bridge MTU and outer size not tested), line 89 (`gnb` restart), line 75 (owner-supplied), line 71 (cause name), line 21 (caption key roles). The three non-tcss colours are no longer in `site/src` (grep, 0 hits). Line 90 (E6(c)/R4) and line 91 (bridge MTU, outer GTP-U size) are in "What was not tested".
- **DEVLOG #101 aside fixed** (`DEVLOG.md:834-840`: R1 had two).

### 2. Claims checked against captures (this review)
- **#101 text (`DEVLOG.md:834-840`, `run-1-proxmox/README.md:46-48`): correct.**
  - `deregistration-052112`: 0x42 RAN 6 at frame 721, then 0x64 with cause 101 at frame 727.
  - `deregistration-052411`: 0x42 RAN 17 at frame 721 (epoch ...258.228410), then 0x64 with cause 101 at frame 727 (...258.436644).
  - `initial-registration-052444` frames 405/407 are a UEContextRelease Command/Complete on RAN 17 with Cause nas normal-release (0). Frame 405 is at ...288.239628, and 288.239628 - 258.228410 = 30.011 s, so "30.01 s" is right.
  - The T3550 reading is labelled as inferred in both places. That fits TS 24.501 §5.5.1.2.8: T3550 is retransmitted on each expiry and the procedure is aborted on the 5th expiry, so 5 x 6 s = 30 s (T3550 default 6 s, §10.2). The Open5GS T3550 setting in this lab is not verified.
  - "not 13" (`:839`) is right: 10 completes + 3 re-registrations would give 13, and only RAN 10 completed.
- **#101 counts in other runs (`DEVLOG.md:839-840`): correct.**
  - R2 `-174450` frame 723. R2b `-202418` frame 687. R3 `-231306` frame 703. Pre-rollback `-220759` frame 723, RAN 6.
  - R2c has 0. Each one has cause 101, and no other 5GMM STATUS appears in any of these runs.
- **E4 breakdown (`summary.md:24`): consistent with the pcaps.**
  - R2c: 20 initial-type Registration requests in InitialUEMessage (15 scenario + 5 GUTI re-registrations) and 15 Registration completes. That equals +20/+15.
  - R3: 12 and 8 (9 + 3; 6 + 3 - 1 for the #101). That equals +12/+8.
  - The counter semantics are Open5GS v2.8.0 `gmm-sm.c` (REQ on every initial-type request, SUCC on Registration complete), as in my R1 review.
- **GTP-U (`summary.md:22`).**
  - R2c 80/80/20 and R3 80/80/80 match `ping-gtpu.json`.
  - These are raw frame counts. The JSON notes they are not de-duplicated, so 80 = 40 echo request + 40 echo reply frames.
  - The tracer pcaps themselves are on the VM, so I did not verify them.
- **Post lines 96-97, R1 README and summary scenario claims.** Unchanged since my post review, and still consistent: #7 in every reject, #21 10/10 per 5-suite run and 6/6 in R3, re-registration counts 3/4/5/5/3.

### 3. E9 wording (checked against `score.json`, `run2/score.json`, `run2/preregistration.md`, the haiku reader files)
- The scores match in the post (lines 82-85), DEVLOG (`:849-857`) and summary (`:13`, `:32`):
  - opus 5/6 strict in attempt 1, then 6/6;
  - sonnet the same;
  - haiku 4/6 in both attempts, with strict Q1 = 0. I read the reader-3 Q1 answer myself: "5G standalone (SA) testbed project", with no Open5GS, UERANSIM or gNB/UE in that answer.
  - Lenient: 6/6 for all readers.
  - `readers_pass_strict` is 2 in both attempts.
- The summary (`:13`) states the 2-of-3 reading correctly. It says the all-3 rule was the evaluator's pre-registered choice, that it is stricter than the plan's "Readers: ≥ 2" (`project/plans/L0.md:364`), and that the owner has not ruled.
- No file claims E9 passed. Findings N1-N2 cover what is missing.

### BLOCKING-for-close
None. No claim in the post, DEVLOG or summary goes beyond the captures on a procedure, cause value or count. The points below are accuracy or completeness issues.

### Non-blocking
- **N1. `site/src/pages/blog/proxmox-migration.md:81`.** The threshold is given as "at least 5 of 6 per reader with Q1 correct", and the post never says that 2 of 3 readers passed the strict reading in each attempt. Nor does it say that the FAIL depends on the evaluator's pre-registered rule that all 3 readers count, while the plan says "Readers: ≥ 2". This makes the result look worse, not better, so it is not an over-claim. But a reader cannot see why 2 passing readers is a FAIL. Suggest: "2 of 3 readers passed strictly in each attempt. The verdict is FAIL under the evaluator's pre-registered rule that all 3 readers must pass. The plan's 'at least 2 readers' wording could be read as 2 passing readers, and the owner has not ruled on it."
- **N2. `DEVLOG.md:851` and `:854`.** "failed the strict reading: 2 of 3 readers passed" has the same gap. Add "under the pre-registered rule that all 3 readers count".
- **N3. `DEVLOG.md:849`.** The static check commits are stated as `8b9cab9` and `fb1bab2`. `8b9cab9` is the attempt-1 evidence commit. The tested commit is `100fd30` (`readme30s/score.json` `git_sha`; `summary.md:31`).
- **N4. `summary.md:13` and `readme30s/score.json` `preregistered`.** For attempt 1, "made before the readers ran" is the evaluator's own statement inside the evidence file. No pre-run commit records it: the first E9 commit, `8b9cab9`, already holds the results. Attempt 2 has a real pre-run commit: `fb1bab2` at 01:00:54Z, and the readers started at 01:00:59Z. Suggest "self-reported for attempt 1; committed before the run for attempt 2".
- **N5. Stall 1 "at its first rotation": `site/src/pages/blog/proxmox-migration.md:40`, `DEVLOG.md:728-732`.**
  - `project/notes/L0.md:940` says, for the pre-R1 stall (last data 04:53:42Z), "Stall cause: not proven (earlier rotations with the same gzip failure did not stall)". So in that case the gzip failure did not stall the capture at the first rotation. It also did not stall it at every rotation.
  - Stall 1 also happened more than "twice" (`DEVLOG.md:731`): T7, before R1, at 15:06:37Z after `-Z root`, and again after the 15:12Z probe restart (`notes:942`).
  - Suggest: "at a rotation (not every gzip failure stalled it)".
  - This matters for Stage 7: it makes the trigger→spin link non-deterministic for stall 1, which fits "mechanism not known".
- **N6. `DEVLOG.md:754`.** "Stall 2 below found a trigger that fits it" goes a little further than the evidence. The child-exit explanation for stall 1 was never tested: no repro with `-z` under `shareProcessNamespace`. The post's "may be the same unexplained effect" (line 40) is the right strength.
- **N7. `DEVLOG.md:772`.** "about 4 minutes after the spin began". The notes give a scenario tcpdump stop at 17:44:31Z and the probe kill at 17:49:13Z (`notes:1765`). That is 4 min 42 s, so "about 5 minutes" is closer. The source phrase "after about 4 minutes" (`notes:1778`) refers to the repro.
- **N8. `DEVLOG.md:829`.** It still says #21 appears "before every SUCI registration". The reject UE also registers with SUCI and gets #7 with no authentication. The post (line 97) has the precise wording. Copy it.
- **N9. `DEVLOG.md:837`.** The 30.01 s release is seen in a different pcap (`initial-registration-052444` frames 405/407). DEVLOG names only the deregistration pcaps. The evidence pointer to the R1 README O-1 (`:841`) covers it, so this is optional.
- **N10. `DEVLOG.md:827-828`.** Only R1's leftover PDU session is mentioned. R2c's 5/5 re-registered UEs that also set up a PDU session (post line 96, my TN2) are not in the DEVLOG or in the R2c README. Stage 7 baseline input.
- **N11. `project/reports/L0/eval/summary.md:1`, `:3`, `:15`.**
  - The committed file still calls itself a "DRAFT, to be moved to ...". It also says it "has not been reviewed by the evaluator after saving".
  - The STATUS correction note at `:15` is stale: `project/STATUS.md` now records the non-allowlisted scans as done.
  - The numbers I could check (E2-E4 and E9) are right. The header still needs the evaluator's sign-off, or a provenance line saying who put the file in `eval/` and in which commit (`0f24789`).
- **N12. `summary.md:22`.** Add "raw, not de-duplicated" after the GTP-U frame counts, as the JSON says.
- **N13. `site/src/pages/blog/proxmox-migration.md:6`.** "three evaluator runs later": there were five runs (R1, R2, R2b, R2c, R3) under three run IDs. Optional: "five evaluator runs (three run IDs)".
- **Outside telco scope, for the evaluator or the security reviewer:** `.claude/settings.json` changed after the E6(a) close run (`git diff --stat 24fbf52 0f24789`). `summary.md:58-59` says `.claude/**` is an allowed path, but a re-run is needed after any non-`project/**` change. Someone should confirm that this change does not need a re-run.

### Not verified in this final review
- The tracer's own pcaps (GTP-U frame counts, TEIDs, outer packet size). They are on the VM.
- The AMF log and the T3550 retransmissions themselves. The T3550 value configured in Open5GS: I assumed the default of 6 s.
- Why UERANSIM sends #101. The root cause of #21.
- The lab-ops notes (15:12Z probe kill, 17:44:31Z/17:49:13Z, 2/2 and 4/4 repro counts, 15 denials). I took them from `project/notes/L0.md` only.
- The E9 reader answers beyond Q1 of reader 3. I did not re-score the other answers.
- When the attempt-1 all-3 rule was fixed (see N4).
- The rendered site. No build or browser run in this review.
- Spec text: TS 24.501 §5.5.1.2.8 and §10.2 are cited from memory and were not re-read.
