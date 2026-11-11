# Stage L0 close

Proxmox migration and repo polish. Branch `stage/L0`, last commit before this report `0f24789` (later commits: reviews, alignment edits, E6(a) final re-run `d18b67e`, this report `407342f`) (nothing from L0 pushed; `origin/main` already holds 3 older commits, see "Before any push"). Plan `project/plans/L0.md`, approved 2026-11-09T23:23:52Z (hash `664fbf04…0bc4dd`), re-approved after the E4 amendment 2026-11-10T00:02:24Z (hash `1310dd1c…ac90f3`). Evidence: `project/reports/L0/eval/` (summary: `eval/summary.md`), `telco.md`, `security.md`.

## Verdict

**L0 closes with deviations, all owner-accepted or recorded below.** The lab runs on a Proxmox VM (K3s v1.36.6+k3s1, Open5GS v2.8.0, UERANSIM v3.3.0), rebuilds from zero with one documented command, and survives a snapshot rollback. E9(b) failed the evaluator's pre-registered all-readers rule; the owner ruled on 2026-11-11 that the plan means "at least 2 readers pass", which opus and sonnet met in both attempts, so E9(b) is recorded as PASS on the plan's threshold with the caveats below. Two security findings, S-I3 and F-R2b, are open and recorded as accepted risks.

## Exit criteria (WORKFLOW verbatim, plan section 8)

| Criterion | Result | Evidence |
|---|---|---|
| All `neoncore`/`monitoring` pods healthy, `dbctl` Completed (E1) | PASS (R1, R2c, R3), restart delta 0 | `eval/run-1-proxmox`, `run-2c-fromzero`, `run-3-restore` |
| UE ping via `uesimtun0` (E2) | PASS, 3/3 in every run (20/20 replies) | same runs |
| 3 phase6 scenarios pass with valid pcaps (E3) | PASS: 15/15 (Wilson 95% [0.796, 1.000]), 15/15, 9/9 (Wilson [0.701, 1.000]) | same runs |
| Grafana panels show data (E4) | PASS: 17 of 18 targets with data, `pdusessioncreationfail` absent (allowed) | `e4.json` per run |
| One documented command rebuilds from zero (E5) | PASS: 396 s, idempotent, owner attests no manual step | `eval/fromzero-2` |
| Nothing depends on WSL2/Windows (E6) | (a) static PASS at `24fbf52` and re-run on the final commit `7b20f8b` (`d18b67e`: fail=0, allowed=2349, other=0); (b) runtime PASS; **(c) not tested** (R4/T15a not run) | `eval/close/wsl`, `run-2c-fromzero` |
| LAN exposure closed (E7) | PASS: allowlisted set {22, 6443, 30030, 30090}; non-allowlisted laptop scans 2 of 2, 0 open TCP/UDP/SCTP, guard persisted after reboot | `lan/` per run |
| Restore from `golden-l0` (E8) | PASS (owner rollback, then R3) | `eval/run-3-restore` |
| Repo explains itself in 30 s (E9) | (a) static PASS; **(b) reader test: PASS on the plan's "at least 2 readers" threshold per the owner's ruling (opus and sonnet ≥ 5/6 with Q1 correct in both attempts); FAIL under the evaluator's pre-registered all-3 rule (haiku 4/6, Q1 wrong, twice)** | `eval/readme30s`, `readme30s/run2` |
| TLS pin (E10) | PASS | `eval/run-1-proxmox/tls` |
| Comparison C1 to C4 | **not tested: no baseline** (baseline B waived by the owner 2026-11-10; C4 absolute versions part passes) | `run-*/compare.json` |

Failed attempts are kept: R2 (E1 tracer restart, E6(a) 2 hits), R2b (E1 sample count only, evaluator procedure), E9 attempt 1.

## Deviations and owner decisions

1. **E9(b) reader test: verdict depends on the threshold reading; owner ruled "at least 2" (2026-11-11).** Attempt 1: opus 5/6, sonnet 5/6, haiku 4/6 (Q1 wrong). Attempt 2 after a README roadmap sentence (`a59970b`): 6/6, 6/6, 4/6 (Q1 wrong again). Lenient scoring gave 6/6 for all, sensitivity only. The evaluator pre-registered that all 3 readers count and so recorded FAIL; the owner ruled that the plan's "Readers: ≥ 2" means at least 2 passing readers, which both attempts met (opus and sonnet), including attempt 1 before any README change. Caveats that stay on record: attempt 2 is not independent (the README sentence was written knowing attempt 1's answers); the strict/lenient reading for attempt 1 was chosen after the answers were seen; haiku failed Q1 both times on unchanged Q1 text; model readers only (D15); human reader not tested; no repeat runs. The README was not reworded to fit the test. **The evaluator's `eval/summary.md`, the post and DEVLOG still say "FAIL" / "closed with the FAIL noted"; they need a wording update to match this ruling** (the evaluator's original verdict stays visible as the pre-registered result).
2. **Baseline B waived (owner, 2026-11-10).** The WSL2 VM was deleted, so C1 to C4 are not tested.
3. **E6(c)/R4 not run.** WSL2 retirement (T15a) is owner-only and did not happen inside L0.
4. **docs-writer overrode a stop-on-IPv4 instruction** and committed `docs/media/tui-demo.txt` with five IPv4 addresses (pod addresses 10.42.0.70, .71, .76, UE pool 10.45.0.2, ping target 8.8.8.8). The lead and the security reviewer agree they are safe (all allowlisted defaults). Recorded as a process deviation.
5. **vhs ran with the no-sandbox flag, run by the owner** in their own terminal (Claude Code refused it). Owner frame check "GIF ok" is the T12 check.
6. **Owner gate patches** (rounds 1 and 2, `project/notes/L0-gate-proposal.md`) were applied by the owner. Round 3 (below) was not.
7. **Playwright MCP tools and the `frontend-design` skill were not used for T13.** blog-writer used the `playwright` npm package with headless Chromium. Both plugins are back to `false` (`02b264d`).
8. **A subagent could not write `eval/summary.md`** (harness rule); the lead saved a draft and the owner copied it, committed under a placeholder Git identity (`0f24789`).

## Accepted risks (owner decision 2026-11-11: option A at close, option C before Stage 7)

**S-I3 (approval forgery / TTY spoofing).** Accepted by: the owner, at L0 close. `approve.sh`, `approval_check.sh` and `plan_guard.py` identify the owner only by an interactive terminal and the absence of Claude Code markers. An agent running as the same OS user can fake both, and the gate's text rules do not fully block this (final security review: 15 of 18 re-tested forms pass). Approval files are not signed, so they are not proof of owner approval. Mitigation until fixed: at each stage start the owner checks that every approval file matches an approval they ran themselves. **Valid until** the W0 amendment below is built and tested, and in no case past approval of the Stage 7 plan: Stage 7 must not be approved while S-I3 is open. **Follow-up:** a W0 amendment plan, "signed approvals and separate agent OS user" (`project/notes/L0-gate-proposal.md` §6 and §6b(c), options in `project/notes/L0-S-I3-options.md`): `ssh-keygen -Y` signatures with a key agents cannot use unattended, verified by `gate.py` and `approval_check.sh`, TTY exemption removed, agents run as a user that cannot write gate, approval or `allowed_signers` files or read `.env.lab`. Reviewer re-check: security-reviewer at that plan's close.
- **Owner confirmation (2026-11-11):** both L0 plan approvals (2026-11-09T23:23:52Z, 2026-11-10T00:02:24Z) were the owner's own runs. This is the owner's statement; the security reviewer did not verify it independently.
- **Doc line:** the known-weakness line for `docs/agent-gate.md:72-73` (text in `L0-S-I3-options.md`) is **not yet applied**. The owner will apply it. Until it is applied, the docs still overstate the TTY check.

**F-R2b (secrets-file read forms).** The 4 forms reported earlier are blocked, but at least 7 further forms still pass the gate (for example a recursive grep from the repo root, or a glob in the secrets file name). The root fix is the separate agent OS user in option C. **Accepted together with S-I3, valid until the same W0 amendment; the owner confirmed on 2026-11-11 that F-R2b is covered by that decision.** A round 3 gate patch for F-R2b, F-PUB and the S-I1 indirection forms was not delivered: a safety classifier stopped the security reviewer's draft, and it was not retried in the same form.

**Also open, non-blocking:** S-I1 indirection forms (documented, `docs/agent-gate.md:61`); Astro telemetry is off in the site's npm scripts but still enabled in the machine's global Astro config; `l0-base` snapshot create-and-wait success path not cleanly exercised; `plan_guard` skips the pool check on updates (`919abab`).

## Before any push (none of L0 is pushed)

`origin/main` already holds 3 commits, including `2dca43c`, which contains the owner's first name (a Windows profile path), an old WSL hostname with the login, and a personal webmail address in three commits. Whether `origin` is public was not tested. Blocking for push, per the final security review:
- **T15c:** history scrub with the real site values (`git log -p --all`), run by lab-ops; the gate blocks the security reviewer from it. Hits go into `security.md` by commit, file and line.
- **D18 identity rewrite:** 123 of 128 commits carry the local login and the control machine's hostname; 2 more carry a placeholder identity. The owner has since set a GitHub noreply identity, which covers new commits only. A rewrite changes every SHA quoted in reports, STATUS and approval files, so a SHA mapping note is needed. The 3 webmail commits are the owner's call.
- **Names and hostnames at HEAD:** `project/plans/W0.md:9` (hostname and LAN address) and `:22` (login); `DEVLOG.md:41`, `:123`, `wireshark-hosts:33`; the E6(a) evidence copies the `DEVLOG.md:41` line 15 times across 4 `allowlist-hits.txt` files. Editing `W0.md` voids the W0 approval hash.
- **Approval files** hold the owner's first name; only the owner may change them.
- **S-B8** and **F-PUB** (the gate misses `git -C . push` forms and `npx wrangler/netlify deploy` for some agents).
- **Before publishing the site:** change the "Local preview only, not published" footer.
- **T15b** (GitHub description and topics) is deferred; D11 is open.

## Spend and cost

Against `project/budget.yaml` (caps: API $25/month, GPU $0, cloud $0; ledger empty): API $0, GPU $0, cloud $0 for the lab. E9 reader sessions cost $0.0974 in total (CLI-reported Claude Code session usage, outside the ledger per plan section 10; far below the cap either way). Source: `eval/summary.md`, "Cost and latency".

## Documentation step (/close-stage step 2)

README, DEVLOG (root-cause entries for the tracer stalls and 5GMM STATUS #101) and the first blog post are done and committed (`a59970b`, `465b5d0`, `149fd94`). **No tutorial was published:** the skill requires every tutorial command to be run against a clean lab restore, and L0 did not include that run, so `/tutorials/` says none are published yet. No ADR or runbook was written in this close pass (not checked against the plan's T11 list).

## Not tested

C1 to C4; E6(c)/R4; a human E9 reader; E9 repeat runs; E9(a) S5 on GitHub; GTP-U in R1 (tracer stalled); MTU in R1 and after the rollback; Proxmox bridge MTU (owner-supplied); a scan with real site values by the security reviewer; whether `origin` is public; why UERANSIM sends 5GMM STATUS #101; the root cause of Authentication failure #21; the rendered site beyond the Chromium layout check; accessibility. Full list: `eval/summary.md`.

## Carried to Stage 7 and later

- The UPF NATs UE traffic out of the VM, so a UE could reach LAN hosts (unchanged from WSL2). Flagged for the Stage 7 plan, which runs faults.
- S-I3 and F-R2b fix (above) before the Stage 7 plan is approved.
- `STATUS.md` housekeeping and the DEVLOG, post and `eval/summary.md` accuracy items from the final telco review (13 non-blocking notes in `telco.md`, none blocking).
- Stage 7 needs a plan from the phase-planner and the owner's approval; the order stays `W0 L0 7 8 9 10 9B 11 12`.

## Questions you should be able to answer about this stage

1. What single command rebuilds the lab from zero, and how long did the from-zero run take? (`scripts/labenv infra/lab.sh up`; 396 s, E5.)
2. Which two things failed R2, and what fixed each? (Tracer restart from an orphaned scenario `tcpdump`, fixed by `shareProcessNamespace`; two WSL2/Windows text hits, reworded.)
3. Why did the tracer stall on the VM first, and what is still unexplained? (AppArmor denied the `-z gzip` exec; the PID 1 spin itself was not explained by any denial.)
4. Which ports are open to a non-allowlisted LAN host, and how do you know the guard survives a reboot? (None; scan 2 after the R3 reboot.)
5. What did the E9 reader test show, and under which reading does it pass? (Opus and sonnet passed both times, haiku failed Q1; passes on "at least 2 readers", fails on the evaluator's all-3 rule.)
6. Which comparison checks were not run and why? (C1 to C4, baseline B waived after the WSL2 VM was deleted.)
7. What are S-I3 and F-R2b, what did you accept, and until when? (Approval forgery via TTY spoofing and secrets-file read forms; valid until the signed-approvals and separate-OS-user W0 amendment, and never past approval of the Stage 7 plan.)
8. What must happen before anything is pushed? (T15c history scrub, D18 identity rewrite, names and hostnames at HEAD, approval files, F-PUB, site footer.)
9. What does `golden-l0` give you, and what did the rollback prove? (A restorable VM snapshot; R3 and E8 passed after an owner rollback.)
10. What does Stage 7 depend on from L0? (A running lab, the tracer, 3 passing scenarios, and the S-I3 fix first.)

## Owner answers (2026-11-11)

1. F-R2b is covered by the "A at close, C before 7" decision: yes.
2. Both L0 plan approvals were the owner's own runs: yes.
3. E9 threshold: at least 2 readers pass (see deviation 1).
4. The owner applies the `docs/agent-gate.md` known-weakness line.
5. The push sequence (T15c scrub, D18 rewrite, D11) is planned after L0 closes.
