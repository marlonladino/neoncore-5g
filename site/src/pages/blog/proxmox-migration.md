---
layout: ../../layouts/Post.astro
title: "Moving a 5G core lab from WSL2 to Proxmox"
date: 2026-11-10
stage: "Stage L0"
summary: "Stage L0 moved the NeonCore lab from WSL2 to a Proxmox VM built by Terraform and Ansible. Two tracer stalls, an end-of-life Debian image and five evaluator runs (under three run IDs) later, it comes up from zero with one command."
---

NeonCore is a 5G standalone testbed: Open5GS network functions, UERANSIM as the RAN and UE, a custom UPF build, a Prometheus and Grafana stack, and a terminal control center, all on single-node K3s. It started life inside WSL2 on a Windows laptop. Stage L0 moved it onto a Proxmox VM and made the whole thing rebuildable from the repository.

## What was built

- **A VM from code.** Terraform clones a cloud-init template into a VM (4 vCPU, 8 GiB, 40 GiB disk). Ansible configures the guest: base packages, kernel settings, Docker, K3s `v1.36.6+k3s1` (pinned) and a host firewall.
- **One entry point.** `infra/lab.sh` runs `up`, `deploy`, `start`, `stop`, `snapshot`, `status` and `verify`. The `verify` step checks the pods, a UE ping through the GTP tunnel and the N3 packet counters.
- **A pinned Proxmox TLS leaf.** The API endpoint is only trusted if its leaf certificate matches a pinned fingerprint. A deliberately wrong pin makes the check fail, with no Terraform or API call made (evaluation item E10).
- **A host firewall guard.** An `nftables` table on the VM allows only the SSH, API server, Grafana and Prometheus ports from one admin address. All site values (addresses, VM id, pool, storage) live in a git-ignored env file; the repository holds placeholders.
- **Docs and this site.** `docs/lab-proxmox.md`, a rewritten README and the terminal demo below.

<figure>
  <img src="/media/tui-demo.gif" alt="Recording of the NeonCore terminal control center running against the lab, in a terminal window" width="900" />
  <figcaption>The NeonCore terminal control center, recorded with vhs from <code>docs/media/tui-demo.tape</code> against the live lab. Keys pressed: <code>r</code> and <code>l</code> (views), <code>p</code> (a UE ping, which sends user-plane traffic) and one <code>s</code> initial-registration run, which also creates a scenario UE pod. The terminal theme in the recording is vhs's own; this site's palette uses only colors from the TUI's stylesheet, <code>phase5/neoncore_cli/neoncore.tcss</code>.</figcaption>
</figure>

## What broke

Every item below is from the project's `DEVLOG.md` Stage L0 section and the raw build notes.

### The first `terraform apply` took 15 minutes

The apply created the VM in 15m12s by the provider's own creation message, inside an apply of 911 s wall time (03:43:53Z to 03:59:04Z in the build notes). The two figures come from different sources and do not add up exactly. It was not cloud-init. The provider waits for the QEMU guest agent to publish network interfaces, the template image had no agent, and the wait ran to the provider's default 15-minute timeout. Ansible now installs `qemu-guest-agent` and `main.tf` sets `agent.timeout = "30s"`. A later plan took 0.7 s.

### The UPF image would not build: Debian bullseye is end of life

`docker build` of the custom UPF stopped in the `debian:bullseye` builder stage with exit 100. About 50 package files returned 404 on the security mirror, while the same file returned 200 on `archive.debian.org` (checked for one `curl` package). The owner chose to leave the repository Dockerfile unchanged and have the Ansible role rewrite the apt sources in the VM's copy only. The consequence is stated plainly: that builder stage gets no more security updates, and the build is not bit-identical to the old one. The runtime image is the stock one, and `open5gs-upfd -v` in the built image reports v2.8.0.

### The tracer stalled twice, from two different triggers

The tracer is a pod running a rotating `tcpdump` for the whole lab. Neither of these two stalls happened on WSL2. An earlier, unexplained WSL2 stall is recorded in `DEVLOG.md`: `tcpdump` was PID 1 and Running, and wrote nothing for 45+ minutes; its root cause was not isolated.

**Stall 1: a denied `gzip` exec.** The capture stopped at a file rotation; `tcpdump` sat at about 100% of one core and logged `execlp(gzip, ...) failed: Permission denied`. Ubuntu 24.04 loads an enforcing AppArmor profile for `tcpdump` that applies inside the container. The profile allows exec of `/bin/gzip`, `/usr/bin/gzip`, `/bin/bzip2` and `/usr/bin/bzip2`, and in the tracer image `gzip` is a symlink to `/bin/busybox`, which AppArmor resolves and denies (15 identical kernel-log denials). The stall was not tied to the first rotation: in the pod where it was first investigated, earlier rotations had the same `gzip` failure and did not stall, so why it stalled when it did is not proven. It happened more than twice, including again after a `-Z root` attempt. AppArmor explains the denied `gzip` exec. It does not explain the spin that followed; the spin may be the same unexplained effect as in stall 2. The WSL2 kernel has no AppArmor, so it ran unconfined there. Fix, chosen by the owner: no `-z`; the capture script's 60 s loop compresses rotated files itself, and a liveness probe fails the container when the newest file is older than 120 s. After the fix, 3 rotations were verified with 0 restarts.

**Stall 2: an orphan and PID 1.** The first evaluator run after the from-zero rebuild (R2) failed on a tracer restart. R1, the first full run on the VM, had passed. The tracer ran `exec tcpdump`, so `tcpdump` was PID 1. The scenario runner starts its own per-scenario capture through a short-lived shell; when that shell exits, the scenario `tcpdump` is reparented to PID 1, and when it later exits, PID 1 goes to state R and stops writing. This reproduced in 2 of 2 tries on the live pod. The fix is `shareProcessNamespace: true`, so the pause container is PID 1 and reaps orphans. Verified in 4 of 4 repro cycles, with 3 rotations and 0 restarts. What is not known: the code path inside `tcpdump` 4.99.6 that spins. The trigger and effect are proven, the mechanism is not.

### Smaller breakages

- **`verify` said "no ping result" on a working lab.** The parser required text before the packet count in ping's summary line. An anchored regex fixed it.
- **`start.sh` raced the UPF pod.** After a clean stop, `kubectl wait` failed at once because the pod did not exist yet. A bounded retry (300 s) replaced the bare wait.
- **The Proxmox API stalled at night.** A hung mount of unavailable NFS storage stalled the host's status daemons. No agent changed Proxmox; the owner restored the storage.
- **A stale kubeconfig.** Not hit live: a from-zero rebuild would have kept the old cluster's CA unless the copy uses `force: true`.

## The numbers

An independent evaluator agent defined the pass criteria before the build and ran them; the builders could not change them. Paths below are under `project/reports/L0/eval/`.

<div class="tablewrap">

| Run | What | Result | Source |
|---|---|---|---|
| R1 | first green deploy | PASS: E1 pods stable over 2724.4 s with 0 restarts (the tracer capture was stalled for all of R1, stall 1, so GTP-U is not tested in R1); E2 ping 20/20 in each of 3 runs; E3 scenarios 15/15, Wilson 95% CI [0.796, 1.000] | `run-1-proxmox/README.md` |
| R2 (attempt 1) | after from-zero build | FAIL: E1 tracer restart (stall 2) and E6(a) 2 text hits | `run-2-fromzero/README.md` |
| R2b | same VM | FAIL on sample count only: 25 soak samples against 26 required; evaluator procedure, not the lab | `run-2b-fromzero/README.md` |
| R2c | full rerun | PASS: 25 samples over 1501.5 s, 0 restarts; E2 3/3; E3 15/15; E4; E7 | `run-2c-fromzero/README.md` |
| R3 | after snapshot rollback | PASS: 1021.2 s window, 0 restart delta; E2 3/3; E3 9/9, Wilson [0.701, 1.000]; E7 after reboot | `run-3-restore/README.md` |

</div>

Other measured values, all from R2c unless noted:

- **From zero:** the second from-zero attempt took 396 s wall (19:16:48Z to 19:23:24Z), exit 0, Terraform 1 added / 0 changed / 0 destroyed, Ansible `ok=41 changed=17 failed=0` then `ok=17 changed=7 failed=0`. All workload pods were Ready after 342 s. A rerun converged with 0 changes (`fromzero-2/README.md`, `fromzero-2/timing.json`).
- **Ping through the tunnel:** 20/20 replies in each of 3 runs, round trip p50 between 5.06 and 5.26 ms, p95 between 6.05 and 11.4 ms. N3 counters rose by 20 in and 20 out in each run.
- **Scenarios:** 15/15 pass, suites took 41 to 43 s each. The registration-reject scenario returned cause 7 (5GS services not allowed) in 5 of 5.
- **Dashboards:** 10 panels over 18 targets, 17 with data, 6 of 6 Prometheus targets up.
- **Network exposure:** from the allowlisted address, the open TCP ports were exactly 22, 6443, 30030 and 30090, with 65531 filtered. From a LAN laptop not on the allowlist, 0 of 65535 TCP ports were open; the scan after a reboot (R3) also passed.
- **MTU:** pods 1450 on `eth0`, `uesimtun0` 1400, VM NIC 1500. A 1372-byte do-not-fragment ping was received 3 of 3 in each of the 3 runs (informational, no threshold). 1372 + 8 + 20 = 1400, so this only shows the inner packet fits `uesimtun0`. Whether the outer GTP-U packet was fragmented, and the Proxmox bridge MTU (1500 is owner-supplied), are not tested.
- **Rollback:** the owner's rollback to the `golden-l0` snapshot took 1 s on the Proxmox task log (owner-supplied; the evaluator did not measure it) (22:32:00Z to 22:32:01Z); after boot and `start.sh` the lab passed R3 (`run-3-restore/README.md`).
- **Cost:** $0 estimated and actual.

## What was not tested

- **Before and after comparison.** The plan wanted WSL2 baseline numbers. The WSL2 VM had already been deleted, so every C1 to C4 comparison is "not tested: no baseline" (owner waiver). This post makes no claim that Proxmox is faster or more stable than WSL2.
- **Reader test (E9): passes on the plan's threshold, fails the evaluator's stricter pre-registered rule.** Static checks S1 to S6 on the README passed. The test of three model readers (fresh sessions, no tools, no repo access; opus, sonnet, haiku) answered six questions about the README and the demo frame. A reader passes with at least 5 of 6 and Q1 correct, scored strictly: each answer on its own text. In both attempts, 2 of 3 readers passed strictly (opus and sonnet), and haiku failed Q1 (`readme30s/score.json`, `readme30s/run2/score.json`). The plan's threshold says "Readers: >= 2". The owner ruled on 2026-11-11 that this means at least 2 readers pass, so E9(b) passes on the plan's threshold. The evaluator had pre-registered that all 3 readers count, so under that rule it is a FAIL, and the evaluator's original verdict stays on record (`project/reports/L0/close.md`, deviation 1).
  - Attempt 1: opus 5/6, sonnet 5/6, haiku 4/6 with Q1 wrong. Opus and sonnet lost Q6 because no roadmap or stages were named. Haiku's Q1 answer named none of Open5GS or UERANSIM, though its Q3 answer did.
  - Attempt 2, after one sentence naming the staged roadmap was added to the README: opus 6/6, sonnet 6/6, haiku 4/6 with Q1 wrong again (and Q6 lost, because it said it did not know which stages are done).
  - Attempt 2 was not independent of attempt 1. The sentence was written with knowledge of the attempt-1 answers and aimed at Q6, so the Q6 improvement is not an independent measure.
  - The strict reading for attempt 1 was chosen after the answers were seen.
  - Scored leniently (the whole answer sheet counts), all three readers scored 6/6 in both attempts. That reading was a sensitivity check only.
  - The README was not reworded to fit the test. Each reader ran once per attempt, so repeat-run variation is not tested.
  - Readers were models only. No human reader: not tested.
- The non-allowlisted external scan ran from one LAN host only.
- The cause of the `pcf` and `udr` restarts after each `start.sh` (1 to 2 each, everything Running at the end; `gnb` also restarted once in the R3 boot) is not tested; the notes attribute it to startup order.
- E6(c)/R4: not tested.
- The Proxmox bridge MTU (not measured) and the size of the outer GTP-U packets on N3: not tested.
- Mounting NFS storage with `soft,nofail,x-systemd.automount` is advice in the lab docs; it was not applied or tested.

## Things the evaluator noticed that Stage 7 must deal with

- After a UE-originated deregistration the UERANSIM 3.3.0 UE re-registers by itself, about 200 ms after the context release. Deregistration pcaps showing it: R1 3 of 5, R2 4 of 5, R2b 5 of 5, R2c 5 of 5, R3 3 of 3. In R2c all 5 re-registered UEs also set up a PDU session.
- Authentication failure cause #21 (synch failure) shows before every SUCI registration that reaches authentication (the reject scenario is rejected with #7 before that): 10/10 in R1, R2, R2b and R2c, and 6/6 in R3. The network resyncs and registration succeeds. The cause was not verified. A fault-injection stage has to tell this harmless #21 from an injected one, and a wrong K or OPc must show as #20 (MAC failure), not any authentication failure.

## History

The old lab ran inside WSL2 on Windows. The WSL2 notes in `DEVLOG.md` (a MongoDB volume that was never persistent, a clock drift that traced back to the Windows host, an `ogstun` interface missing from every manifest) stay in the repository as history.
