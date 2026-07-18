# NeonCore 5G — Development Log

This is the phase-by-phase engineering record: every bug found, every deviation from the
original spec, and why. `README.md` is the polished getting-started document; this file is the
detailed "how we actually got here" — kept for anyone extending the project who hits a similar
wall and wants to know if it's already been solved.

## Environment

- Host: Windows PC, AMD Ryzen 7 5800H, 16GB RAM
- WSL2 (Ubuntu 24.04 "noble"), memory cap ~6.2GB (not resized — user chose to keep default cap)
- Docker: native docker-ce in WSL2 (not Docker Desktop integration)
- K8s (Phase 1+): K3s single node, Docker driver, Multus CNI

## Deviations from the original spec (and why)

- **AUSF is included** even though the spec's NF list only names NRF/AMF/SMF/UPF/PCF/UDM/UDR.
  AUSF performs 5G-AKA authentication — without it the UE cannot authenticate, so it's a hard
  functional requirement for "UE attaches successfully," not an optional extra.
- **BSF is included** even though the spec's NF list omits it. Open5GS 2.8.0's PCF
  unconditionally tries to discover a BSF (`nbsf-management`) during policy association and
  crashes (abort, not a graceful warning) if none is registered — discovered empirically when
  PCF died right as the UE reached the policy-association step. Not optional in practice.
- **NSSF and SCP are omitted.** Not needed for a single-slice, non-roaming, direct
  NRF-discovery topology — the spec's success criteria don't require them, and nothing else
  broke without them.
- **Test PLMN 999/70** (not 001/01) — matches UERANSIM's own default sample configs, which is
  the most widely-tested pairing for this exact stack.

## Known issue: WSL2 clock drift

`dmesg` shows repeated `systemd-journald: Time jumped backwards, rotating.` every ~5-50s —
Windows is periodically suspending/resuming the WSL2 VM's clock. This breaks UERANSIM's
timer-based radio-link-simulation keepalives and causes the gNB↔UE radio link to flap
continuously (visible as repeating `signal lost` / `new signal detected` / occasional
`AMF selection ... failed` in gNB logs), which in turn makes the UE↔UPF data path unreliable
even though control-plane signaling (NG Setup, registration, PDU session establishment) mostly
still succeeds in the calm windows between jumps.

**Likely fix** (not yet applied — user chose to defer): add `vmIdleTimeout=-1` to
`C:\Users\marlo\.wslconfig` under `[wsl2]`, then `wsl --shutdown` from PowerShell and reopen.
This stops Windows from suspending the idle VM, which is the probable trigger for the drift. See
`README.md`'s Troubleshooting section for the full writeup.

## Phase 0 — Bare-metal validation

Directory: `phase0/`

Images (pinned): `gradiant/open5gs:2.8.0` (one image, reused per NF via command override),
`gradiant/ueransim:3.3.0`, `mongo:7.0`.

Services: mongo, dbctl (one-shot subscriber provisioning), nrf, ausf, udm, udr, pcf, amf, smf,
upf, gnb, ue — all on a single `neoncore` bridge network. NF-to-NF discovery is via Docker's
embedded DNS (container name = hostname); no static IPs needed.

Test subscriber: IMSI `999700000000001`, matching UERANSIM's built-in default UE credentials
(K/OPc), provisioned automatically into Mongo by the `dbctl` service on `docker compose up`.

### Run

```
cd ~/neoncore-5g/phase0
docker compose up -d
bash scripts/verify.sh
```

### Bugs found and fixed while validating this compose stack

These will matter again when porting to K8s in Phase 2:

- `amf.yaml` needs `amf.time.t3512.value` explicitly set — Open5GS 2.8.0 fails to start without it.
- The `gradiant/open5gs` image runs as a non-root user; `cap_add: NET_ADMIN` alone does not let a
  non-root process create the `ogstun` TUN device or write `net.ipv6.*` sysctls (Linux ambient
  capabilities aren't propagated across `exec` by default). UPF needed `user: "0:0"` plus, even
  then, the ipv6 sysctl write still failed under plain `NET_ADMIN` — ended up using
  `privileged: true` for UPF in Phase 0. For Phase 2, expect to need an explicit K8s
  `securityContext` (root + NET_ADMIN, possibly SYS_ADMIN) rather than assuming capability-only
  is enough — this is exactly what the spec's Phase 2 check (`kubectl describe pod <upf-pod>` for
  NET_ADMIN) is watching for, so it may need investigation there too.
- PCF crashes (abort, not a graceful error) if no BSF is reachable for `nbsf-management`
  discovery during policy association — BSF is a hard dependency here despite not being in the
  spec's NF list.
- The subscriber's authorized S-NSSAI in Mongo must include the same `sd` value the
  AMF/gNB/UE are configured with, or AMF rejects registration with `No Allowed-NSSAI`. The
  standard `open5gs-dbctl add` command doesn't set `sd` at all — had to add it by hand in
  `scripts/add-subscriber.js`.

### Success criteria (from spec)

- All Open5GS components healthy (nrf, ausf, udm, udr, pcf, amf, smf, upf)
- gNB registers with AMF (NG Setup)
- UE attaches and establishes a PDU session — `uesimtun0` appears inside the `ue` container with an IP
- `docker exec ue ip addr show uesimtun0` and a successful ping through the tunnel to an external host

## Phase 1 — K3s + Multus

Directory: `phase1/`

- K3s installed via `setup/install-k3s.sh`: `--docker` (container runtime, per spec), with
  `--disable=traefik --disable=servicelb` (neither needed, saves RAM).
- Kernel prerequisites (`setup/prepare-k3s-kernel-modules.sh`): `iptable_nat`, `macvlan`, `ipvlan`
  — loaded and persisted via `/etc/modules-load.d/neoncore-k3s.conf`.
- Multus deployed via K3s's built-in HelmChart CRD (`phase1/multus-helmchart.yaml`), chart
  `rke2-multus` from `https://rke2-charts.rancher.io`, with K3s's non-standard CNI paths
  (`/var/lib/rancher/k3s/data/cni/`, `/var/lib/rancher/k3s/agent/etc/cni/net.d`) explicitly set —
  the plain upstream `multus-cni` daemonset manifest assumes standard kubeadm paths and silently
  breaks on K3s if you skip this.
- Validated with a real macvlan `NetworkAttachmentDefinition` + test pod
  (`phase1/test-macvlan-nad.yaml`, applied and torn down after confirming) — the pod came up
  with a genuine `net1@eth0` macvlan interface (`192.168.200.10`) alongside the default flannel
  interface, confirmed via `k8s.v1.cni.cncf.io/network-status` annotation and `ip addr` inside
  the pod.

### Gotcha: `kubectl` needs `KUBECONFIG` set explicitly

K3s symlinks `/usr/local/bin/kubectl` to the `k3s` binary itself. Unlike stock `kubectl`, this
wrapper does **not** default to `~/.kube/config` — it hardcodes `/etc/rancher/k3s/k3s.yaml`
(root-only, 600) unless `KUBECONFIG` is set. Added `export KUBECONFIG=$HOME/.kube/config` to
`~/.bashrc`.

### Success criteria (from spec)

- `kubectl get nodes` shows Ready — confirmed (`pcmarlon Ready control-plane`,
  `docker://29.6.2` runtime)
- Multus pod Running — confirmed (`multus-xptx7 1/1 Running`)
- macvlan/ipvlan interfaces can be created on the node — confirmed via live test pod

## Phase 2 — 5G Core & RAN on Kubernetes

Directory: `phase2/manifests/`. Namespace `neoncore`. Same images/PLMN/subscriber as Phase 0,
ported to Deployments + headless Services (`clusterIP: None`) instead of docker-compose — headless
was a deliberate choice, not a default: this node's kernel has no `nf_conntrack_proto_sctp`
module, so a normal ClusterIP Service could not reliably proxy AMF's SCTP (N2) traffic through
kube-proxy/iptables. Headless services return the pod's real IP via DNS, matching how Docker's
embedded DNS behaved in Phase 0, and sidestep the gap entirely.

Config files (`ConfigMap`s) are the exact same YAML as `phase0/configs/*.yaml`, unmodified —
K8s DNS resolves short service names the same way Docker Compose's DNS did, so no config changes
were needed crossing from Phase 0 to Phase 2.

### Bugs found and fixed while deploying to K3s

- **`command:` vs `args:`**: Kubernetes' `command:` field overrides the container's Docker
  `ENTRYPOINT` (unlike `docker-compose`'s `command:`, which appends to it). Used `command:
  ["gnb"]` / `["ue"]` for the UERANSIM pods initially, which tried to exec a literal `gnb`/`ue`
  binary that doesn't exist — needed `args:` instead so `/entrypoint.sh` (which does env-driven
  config templating and IP autodetection) still runs.
- **UPF forgot its own fix**: initially copied only `NET_ADMIN` + `runAsUser: 0` to the UPF pod
  without the `/dev/net/tun` device mount — copy-paste gap from Phase 0's manifest, not a new
  issue. Fixed with a `hostPath` volume for `/dev/net/tun`.
- **UPF's `NET_ADMIN`-only actually works here** (unlike Phase 0's docker-compose, which needed
  `privileged: true`) — because the open5gs image's `command:` override bypasses its buggy shell
  `entrypoint.sh` entirely in K8s (see point above), so the shell script's failing
  `sysctl -w net.ipv6...` call never runs; `open5gs-upfd`'s own internal tun handling creates
  `ogstun` directly and that only needs `NET_ADMIN`. This satisfies the spec's Phase 2 check more
  precisely than Phase 0 could.
- SMF crashed once on first rollout (`getaddrinfo(upf) failed`) because UPF's headless-service
  DNS entry didn't exist until UPF's pod went Ready — same race as Phase 0, but this time
  Kubernetes' Deployment controller auto-restarted SMF and it self-healed once UPF stabilized, no
  manual intervention needed.

### Success criteria (from spec)

- gNB registers with AMF — confirmed, NG Setup procedure successful (gNB pod logs)
- UE gets an IP and establishes a PDU session — confirmed, `uesimtun0` up with IP (10.45.0.x),
  `PDU Session establishment is successful` in UE pod logs
- UPF pod confirmed running with NET_ADMIN capability — confirmed via
  `kubectl get pod <upf-pod> -o jsonpath='{.spec.containers[0].securityContext}'`:
  `{"capabilities":{"add":["NET_ADMIN"]},"runAsUser":0}` (no `privileged`)

Same caveat as Phase 0: sustained data-plane traffic (ping through `uesimtun0`) is unreliable due
to the WSL2 clock drift described above — re-verified via `dmesg` and a UPF-side `tcpdump`
showing zero GTP-U packets arriving during a failed ping, identical to the Phase 0 signature.
This is a host-level issue outside the K8s manifests.

## Phase 3 — Monitoring & observability

Directory: `phase3/manifests/`. New `monitoring` namespace: Prometheus, Grafana, kube-state-metrics.

- **Prometheus** scrapes two kinds of targets:
  1. Native Open5GS metrics, discovered via `kubernetes_sd_configs` (role: pod) in the
     `neoncore` namespace, filtered by `prometheus.io/scrape`/`prometheus.io/port` pod
     annotations (added to `phase2/manifests/03-nfs.yaml`).
  2. `kube-state-metrics` — Kubernetes-level pod status/restarts for every pod in `neoncore`,
     regardless of whether that NF exports its own metrics.
- **Grafana** (anonymous admin access enabled for local dev convenience — see README's
  hardening notes) auto-provisions the Prometheus datasource and one starter dashboard
  (`phase3/manifests/dashboards/neoncore-5g.json`): pod status/restarts, AMF registrations,
  SMF PDU session establishment (req/succ/fail), UPF active sessions + N3 GTP packet rate, PCF
  policy associations, per-NF process memory.
- Both exposed via NodePort for convenience: **Grafana http://localhost:30030** (admin/neoncore,
  or just continue anonymously), **Prometheus http://localhost:30090**. WSL2's default
  localhost-forwarding means these should also be reachable from a Windows browser directly.

### Finding: only 4 of 9 NFs support Open5GS's native metrics

Assumed initially (per Open5GS docs) that only AMF/MME/SMF support the built-in Prometheus
exporter. Empirically on this build (`gradiant/open5gs:2.8.0`), it's actually **AMF, SMF, UPF,
and PCF** — NRF/AUSF/UDM/UDR/BSF never start a metrics HTTP server at all (confirmed via
`kubectl exec ... -- curl` returning connection-refused, and absence of any `metrics_server()`
log line for those five, vs. a clear one for the four that work). `prometheus.io/scrape` is only
set on those 4 pods to avoid noisy permanently-down Prometheus targets for the other 5.

Also worth noting: the metrics HTTP server binds to the pod's `eth0` IP specifically (per
`dev: eth0` in each NF's config), not to `localhost`/`127.0.0.1` — `curl localhost:9090` from
inside the pod itself fails; must use the pod's actual IP.

The `metrics:` config block (`dev: eth0, port: 9090`) was added to all 9 NF configs in
`phase0/configs/*.yaml` (shared source for both Phase 0 and Phase 2) for consistency, even
though 5 of them don't act on it — harmless, since Open5GS's YAML parser just ignores
config sections a given daemon's code never reads.

## Phase 4 — Network tracing

Directory: `phase4/manifests/`. One `tracer` Deployment in the `neoncore` namespace, backed by a
5Gi `PersistentVolumeClaim` (`local-path` storage class from Phase 1, so files persist on the
WSL2 filesystem under `/var/lib/rancher/k3s/storage/...` across pod restarts).

### Design: single node-level capture, not per-pod sidecars

Rather than a tcpdump sidecar in every NF pod (9+ extra containers, one shared volume each), the
tracer is a single pod with `hostNetwork: true` + `privileged: true`, running `tcpdump -i any` on
the K3s node itself. Since this is single-node and all pod-to-pod traffic already traverses the
node's `cni0` bridge / veth pairs, one capture point on the node sees everything — N2 (SCTP/NGAP,
port 38412), N4 (PFCP, port 8805), N3 (GTP-U, port 2152), SBI (HTTP/2, port 7777), and ICMP (for
Phase 5's UE ping tests) — without touching the NF pods at all. Verified live: restarting the
`ue` pod produced a real SCTP handshake (`INIT`/`INIT ACK`/`COOKIE ECHO` between gNB and AMF)
in the capture; restarting `smf` produced a real PFCP association with UPF. Both decoded
correctly by `tcpdump -r`.

`phase4/manifests/capture.sh` (mounted via ConfigMap) runs `tcpdump` with:
- Filter: `(sctp) or (udp port 8805) or (udp port 2152) or (tcp port 7777) or icmp`
- Rotation: new file every 5 min (`-G 300`) or 50MB (`-C 50`), whichever first
- Compression: each rotated file gzipped (`-z gzip`)
- Retention: a background loop deletes files older than 2 hours (`RETENTION_MINUTES`)

Files land in `/pcaps/neoncore-<timestamp>.pcap[.gz]` inside the tracer pod (backed by the PVC).
Image: `nicolaka/netshoot` (standard network-debugging toolbox — has `tcpdump`, `tshark`, `gzip`).

## Phase 5 — Cyberpunk CLI control center

Directory: `phase5/`. A [Textual](https://textual.textualize.io/) TUI (`neoncore_cli/`), chosen
over raw `curses` because it gives real-time-updating widgets, easy neon theming via CSS, and an
async event loop that keeps the UI responsive while `kubectl` calls run in the background.

Design choice: "deploy/teardown the Kubernetes infrastructure" is scoped to the NeonCore
workload (the `neoncore` + `monitoring` namespaces) — not K3s itself. Tearing down K3s/Multus
from an app-level CLI would be a much more systemic, harder-to-reverse operation than this tool
should own; that stays a manual `setup/` step.

Shells out to `kubectl` via `asyncio` subprocesses rather than using the Kubernetes Python
client — smaller dependency footprint, and it reuses the exact manifest files already validated
in Phases 2-4 instead of re-encoding them as API objects.

### Verified against the live cluster (not just "it imports")

Used Textual's `run_test()` Pilot API (`phase5/smoke_test.py`) for a headless functional check —
mounts the real app, drives real key presses, asserts on real widget content:
- Pod table populated with all 17 live pods across `neoncore` + `monitoring`
- Ping test dispatched a real `kubectl exec` — correctly reported `uesimtun0: No such device`
  for the current UE pod (accurate: that pod is mid-flap from the WSL2 clock-drift issue and
  hadn't completed a PDU session yet — the tool surfaced real state correctly rather than
  swallowing the error)
- **Bug found and fixed**: "latest trace" initially picked a stale, already-rotated `.gz` file
  over a newer file still being actively written, because it sorted by file mtime and `gzip`
  touches a file's mtime at compression time (which can postdate a still-open newer capture).
  Fixed by sorting on the timestamp embedded in the filename instead of mtime.
- Deploy/teardown confirm-dialog bindings dispatch correctly; the actual `kubectl apply`/`delete`
  sequences weren't re-executed by the smoke test to avoid tearing down the working stack — the
  underlying commands are the same ones already manually validated throughout Phases 2-4.

## Phase 6 — Documentation

`README.md` was rewritten from scratch as a polished, onboarding-focused document (architecture,
prerequisites, quickstart, CLI usage, troubleshooting). This file (`DEVLOG.md`) absorbed the
detailed phase-by-phase content the README previously accumulated, so none of it was lost.

## Notes — WSL reset recovery: three bugs the clock-drift symptom was hiding

Context: the user reset WSL2 entirely, then asked to redeploy and retest the stack. Docker and K3s
came back on their own (both are systemd services, started via `/etc/wsl.conf`'s `systemd=true`),
and all 17 pods reappeared `Running`/`Completed` — no `setup/*.sh` rerun needed. But retesting end
to end surfaced three separate bugs, two of which had been silently masked by the known WSL2
clock-drift issue (see [Known issue: WSL2 clock drift](#known-issue-wsl2-clock-drift) above) for
long enough that they were never caught.

### Bug 1: MongoDB had no persistent volume

`phase2/manifests/02-mongo.yaml` ran Mongo with no volume at all — `emptyDir`-equivalent, backed
only by the container's writable layer. The WSL reset bounced the Mongo pod once, which silently
wiped the test subscriber (IMSI `999700000000001`) that the one-shot `dbctl` Job had provisioned
back in Phase 0/2. Since `dbctl` is a `Job` and it already showed `Completed`, it never reran on its
own. Symptom: AMF logged `Registration reject [7]` (5GS services not allowed) and the UE sat
cycling cell-reselection forever, never sending a second registration attempt.

**Fix:** added a `mongo-storage` PVC (`local-path` StorageClass, 1Gi — same pattern as Phase 4's
`pcap-storage` PVC) with a `/data/db` mount, plus `strategy: { type: Recreate }` on the Deployment
(a rolling update would otherwise deadlock trying to attach the same `ReadWriteOnce` volume to two
pods at once). Reprovisioned the subscriber once more by deleting and reapplying the `dbctl` Job,
then verified persistence by deleting the Mongo pod outright — the subscriber survived without
rerunning `dbctl`.

### Bug 2: the clock drift's real root cause was the Windows host, not WSL2's guest kernel

The DEVLOG's original clock-drift writeup assumed Windows suspending an idle VM (mitigated by
`vmIdleTimeout=-1`, already in `.wslconfig`). After the reset, `dmesg` still showed
`Time jumped backwards, rotating.` every ~30-60s from the moment of boot — clearly not an
idle-suspend pattern, since the VM was never idle. Two dead ends before the real cause:

- **First hypothesis (wrong): bad clocksource.** `cat
  /sys/devices/system/clocksource/clocksource0/current_clocksource` showed `tsc` (raw hardware TSC)
  active instead of `hyperv_clocksource_tsc_page` (the correct paravirtualized Hyper-V clock),
  despite the latter being listed as available. Added `kernelCommandLine =
  clocksource=hyperv_clocksource_tsc_page` under `[wsl2]` in `.wslconfig`. After a `wsl --shutdown`
  and reopen, the clocksource was confirmed switched — but `dmesg` still showed the exact same
  jump-every-~55s pattern and `timedatectl timesync-status` still showed a growing negative offset.
  Wrong diagnosis; left in place since it's harmless, but it wasn't the fix.
- **Real root cause: Windows' own clock wasn't syncing.** Compared `date -u` inside WSL against the
  Windows host's own clock (`powershell.exe -Command "[DateTime]::UtcNow..."`, reachable from WSL via
  the standard `/mnt/c/WINDOWS/System32` interop path) — they were **~7.5 seconds apart**. `w32tm
  /query /status` on the Windows side confirmed: `Leap Indicator: 3(not synchronized)`, `Source:
  Local CMOS Clock`, `Last Successful Sync Time: unspecified`. The WSL2 kernel's
  `hv_utils.timesync_implicit=1` boot parameter (visible in `/proc/cmdline`, always present, not
  something this project sets) continuously pushes the Windows host's clock into the guest. With
  the host clock itself wrong and free-running, that push fought every cycle against
  `systemd-timesyncd`'s independent NTP correction inside WSL (which was polling `ntp.ubuntu.com`
  correctly) — that fight, not idle-suspend and not the clocksource, produced the repeating
  "jumped backwards" pattern.

**Fix:** from an elevated PowerShell on the Windows host —
```powershell
w32tm /config /manualpeerlist:"time.windows.com,0x8 pool.ntp.org,0x8" /syncfromflags:manual /reliable:YES /update
Restart-Service w32time
w32tm /resync /force
```
Verified via the Windows Event Log (`Get-WinEvent -LogName System` filtered to provider
`*Time-Service*`), which showed genuine `NtpClient is currently receiving valid time data from
time.windows.com` / `pool.ntp.org` events right after the resync — versus zero new `dmesg` "jumped
backwards" lines over 5+ minutes afterward, and the WSL-side offset converging from -7s to near 0
instead of oscillating. Confirmed functionally: the gNB/UE `signal lost`/`new signal detected`
flapping (previously continuous, every 5-15s) stopped appearing entirely.

**Gotcha:** `w32tm /query /status` run *unelevated* (as this project's Claude Code session had to,
via `powershell.exe` interop with no UAC prompt available) reported `not synchronized` even
*after* the fix had already worked — that specific query needs elevation to read the real internal
state. Trust the Event Log or a live clock comparison against WSL over that unelevated query.

### Bug 3: UPF's `ogstun` interface and NAT were never actually in any manifest

Only visible once Bug 2 was fixed and the radio link stopped flapping long enough for a PDU session
to survive: the UE got a real session and `uesimtun0` came up, but ping through it was 100% loss,
and a `tcpdump` on the UPF pod for GTP-U (`udp port 2152`) during the ping saw **zero packets**.
`kubectl -n neoncore exec <upf-pod> -- ip addr show ogstun` showed the interface existed but was
`DOWN` with no IPv4 address, and `iptables -t nat -L POSTROUTING` was empty. UPF logs showed
repeating `ogs_tun_write() failed (5:Input/output error)`.

`phase2/manifests/03-nfs.yaml`'s UPF container runs `command: ["open5gs-upfd"]` directly (bypassing
the image's shell entrypoint by design, per Phase 2's original finding). `open5gs-upfd` does create
`ogstun` itself, but — contrary to what Phase 2's original testing assumed — it does **not** bring
the interface up, assign it the configured gateway address, or set up NAT/MASQUERADE. Some earlier
interactive session must have done this by hand via `kubectl exec` and it was never captured in any
manifest, so it silently broke on every subsequent UPF pod recreation (including the one caused by
this WSL reset).

**Fix:** added a `postStart` lifecycle hook to the UPF container:
```yaml
lifecycle:
  postStart:
    exec:
      command:
        - sh
        - -c
        - |
          until ip link show ogstun >/dev/null 2>&1; do sleep 1; done
          ip addr add 10.45.0.1/16 dev ogstun
          ip link set ogstun up
          iptables -t nat -A POSTROUTING -s 10.45.0.0/16 -o eth0 -j MASQUERADE
```
(the subnet/gateway match `upf.yaml`'s `session` config). Verified by deleting the UPF pod and
confirming the fresh pod self-configured `ogstun`/NAT with zero manual `kubectl exec` steps.

### Related gotcha: SMF caches its UPF PFCP association by IP

Recreating the UPF pod changes its pod IP. SMF does not notice on its own — it logs `Retry
association with peer failed [<old-upf-ip>]:8805` and `No UPFs are PFCP associated that are suited
to RR`, rejecting every PDU session with `NETWORK_FAILURE`, instead of re-resolving the `upf`
headless-service DNS name. Restarting the SMF pod forces a fresh PFCP association against whatever
UPF IP is currently live.

**Correct recovery order after any UPF pod recreation: UPF → SMF → UE** (UE last, so its
registration/PDU-session attempt lands on an already-fresh SMF↔UPF pair).

### End state

Verified with a real, sustained ping: `30/30` packets, `0%` loss over 14.5s through `uesimtun0` to
`8.8.8.8`, and again `10/10` after a full cold UPF→SMF→UE restart cycle exercising both manifest
fixes from scratch with no manual intervention.

## Notes — Custom UPF build: fixing the N3 GTP packet-count metric gap

With the WSL-reset-recovery notes' fixes in place, the Grafana dashboard's "UPF: N3 GTP data packets" panel still read a
flat `0` for both `fivegs_ep_n3_gtp_indatapktn3upf` and `outdatapktn3upf` — even right after a
confirmed, successful ping through `uesimtun0`. Curling the UPF pod's own `/metrics` endpoint
directly (bypassing Prometheus entirely) confirmed the raw counters themselves were `0`, both
before and immediately after a real ping: not a scrape or dashboard config issue, the metric was
never incrementing at the source.

### Root cause: not a bug, an upstream design tradeoff

Downloaded the exact v2.8.0 source
(`https://github.com/open5gs/open5gs/archive/refs/tags/v2.8.0.tar.gz`) and grepped for the metric
name. In `src/upf/gtp-path.c`, both increment call sites are wrapped in `#if 0` / `#endif`:

```c
/*
 * Issue #2210, Discussion #2208, #2209
 *
 * Metrics reduce data plane performance.
 * It should not be used on the UPF/SGW-U data plane
 * until this issue is resolved.
 */
#if 0
        upf_metrics_inst_global_inc(UPF_METR_GLOB_CTR_GTP_INDATAPKTN3UPF);
        upf_metrics_inst_by_qfi_add(header_desc.qos_flow_identifier,
                UPF_METR_CTR_GTP_INDATAVOLUMEQOSLEVELN3UPF, pkbuf->len);
#endif
```

(and the mirror-image block for the outgoing counter, a few hundred lines earlier in the same
file). The Open5GS maintainers deliberately disabled these two counters at compile time in the
2.8.0 release: incrementing a metric on every single GTP-U packet measurably hurts UPF throughput
on the hot data-plane path, and they didn't want that shipped until the underlying performance
issue was resolved. The stock `gradiant/open5gs:2.8.0` image this project runs is a straight
upstream build, so it genuinely never emits this data — the dashboard panel and this project's
config were both fine.

### Fix: custom-built `open5gs-upfd`, everything else unchanged

Re-enabling the metric means patching the C source and rebuilding the binary — not a manifest or
config change. Given this is a single-UE dev testbed where the per-packet overhead upstream is
protecting against is negligible, and Grafana visibility is worth more here than hot-path headroom
that isn't needed, rebuilt `open5gs-upfd` with the guards removed:

- `phase2/upf-metrics-patch/gtp-path-metrics.patch` — a plain `diff -u` (~20 lines) removing just
  the two `#if 0`/`#endif` pairs, nothing else.
- `phase2/upf-metrics-patch/Dockerfile` — multi-stage build: stage 1 compiles Open5GS v2.8.0 from
  source on `debian:bullseye` (same OS as the `gradiant/open5gs:2.8.0` runtime image, confirmed via
  `/etc/os-release`) using the standard Open5GS build deps (meson/ninja + the usual
  libsctp/libgnutls/libmongoc/etc. -dev packages, matching Open5GS's own
  `docker/debian/latest/base/Dockerfile`), applies the patch, and runs
  `meson build --prefix=/opt/open5gs && ninja -C build install` (the `--prefix` matters: it has to
  match Gradiant's own build so the binary's baked-in default config search path is still
  `/opt/open5gs/etc/open5gs/upf.yaml`, matching what the Kubernetes ConfigMap already mounts).
  Stage 2 starts `FROM gradiant/open5gs:2.8.0` unchanged and `COPY --from=builder`s in only the
  freshly-built `/opt/open5gs/bin/open5gs-upfd` binary — every other NF, user, and runtime library
  in the image is untouched, minimizing the blast radius of the change to exactly the one daemon
  being patched.

Built locally: `docker build -t neoncore-upf:2.8.0-metrics phase2/upf-metrics-patch/` (~80s). Since
this K3s install uses the native `docker-ce` engine directly (`--docker` runtime flag from Phase 1,
not containerd), the locally-built image is immediately usable cluster-side with no registry push —
just needed `imagePullPolicy: IfNotPresent` in the manifest so Kubernetes doesn't try to pull
`neoncore-upf:2.8.0-metrics` from Docker Hub. `phase2/manifests/03-nfs.yaml`'s UPF Deployment now
points at this image instead of the stock one.

### Verification

After swapping the image, deleting the UPF pod, and following the WSL-reset-recovery notes' UPF→SMF→UE restart order:
an 8-packet ping through `uesimtun0` produced
`fivegs_ep_n3_gtp_indatapktn3upf 8` / `outdatapktn3upf 8` on the UPF pod's own `/metrics`, matching
exactly (8 packets each direction), plus real non-zero values on the companion
per-QoS-level volume counters (`indatavolumeqosleveln3upf{qfi="1"} 672`,
`outdatavolumeqosleveln3upf{qfi="1"} 800`). Confirmed the same values reachable live through
Prometheus (`localhost:30090`), not just the pod's raw endpoint — the Grafana panel now reflects
real traffic instead of a flat zero line.

**If `neoncore-upf:2.8.0-metrics` is ever missing** (e.g. after `docker system prune`, or on a fresh
machine): it's fully reproducible, just rerun
`docker build -t neoncore-upf:2.8.0-metrics phase2/upf-metrics-patch/` — no other state is needed.

## Notes — Tracer pod: `tcpdump` can silently stop capturing after heavy pod churn

While demonstrating how to pull and read traces (walking through a full
registration→PDU-session→ping sequence to show it lands in a single capture file, per the
architecture described in [Network tracing](#network-tracing)), the tracer pod's active `.pcap`
file hadn't grown at all in 45+ minutes — despite real, confirmed ping traffic having happened
multiple times in that window. `ps aux` inside the pod showed the `tcpdump -i any ...` process
still alive (PID 1, `Running`, no restarts triggered), so the pod looked completely healthy from
Kubernetes' point of view; it just wasn't actually writing any new packets to disk, and therefore
never hit its `-G 300` rotation trigger either (tcpdump only re-checks the rotation condition when
a new packet is captured, so a capture that's stopped working also stops rotating — both symptoms
disappearing together was itself a clue that packets weren't reaching the process at all, not just
that the file wasn't rotating).

Root cause wasn't isolated further (would require attaching a debugger to a stuck `tcpdump`, not
worth it for a dev testbed), but the likely trigger: this tracer pod's `tcpdump -i any` had been
running continuously since before those notes' flurry of pod deletions and recreations (Mongo, UPF
×2, SMF, UE ×3), each of which tears down and creates fresh `veth` pairs on the node. `tcpdump -i
any` is supposed to pick up interfaces that appear after it starts, but apparently didn't survive
that much churn cleanly here.

**Fix:** simply `kubectl -n neoncore delete pod -l app=tracer` — same pattern as UPF/SMF/UE
throughout those notes. The fresh pod's `tcpdump` started capturing correctly immediately (confirmed:
new file grew from a fresh start to 32KB within a minute just from ambient SBI traffic, then to
210KB after a deliberate UE registration + PDU session + ping sequence).

**How to apply:** if `l` in the CLI (or a manual `ls -la /pcaps`) shows the newest file's size and
timestamp haven't moved in longer than the 5-minute rotation interval despite known recent traffic,
don't assume the capture is just quiet — check `kubectl -n neoncore exec <tracer-pod> -- ps aux`
(process should show real recent CPU time accumulating) and, if in doubt, just restart the tracer
pod. It's stateless from Kubernetes' perspective (the PVC holds the actual capture files, not pod
state), so restarting it costs nothing but a few seconds of gap in capture coverage.

### Related gotcha: never `rm` a `.pcap` file while `tcpdump` still has it open

Hit while setting up a clean single-file capture for a negative-test scenario (unprovisioned-IMSI
registration reject): ran `rm -f /pcaps/*.pcap` against a tracer pod that was already running (to
clear old files before starting a fresh test), then ran the actual test, then pulled the file —
and `/pcaps` was completely empty, as if nothing had ever been captured, even though the test itself
clearly happened (confirmed via `kubectl logs` on the UE and AMF).

Root cause: classic Unix "delete an open file" behavior. `tcpdump -w` had that exact file open for
writing at the moment `rm` ran. `rm` only unlinks the directory entry — `ls` immediately shows the
file gone, but the process holding it open keeps writing into the now-nameless inode with no way to
get it back. Every packet from the negative-test run (and everything after) went into that orphaned
inode instead of anything reachable — and it was gone for good the moment the tracer pod was later
stopped and its file descriptor closed, reclaiming the inode.

**Correct way to get a clean single capture:** don't `rm` files out from under a running tracer.
Either (a) restart the tracer pod first (a fresh pod's `tcpdump` creates a brand-new file — old
files can be safely deleted *before* that restart, or just left alone and ignored, since the CLI's
`l` / a manual listing already show the newest file clearly), or (b) if old files must be removed
from an already-running tracer, do it only when you don't need whatever it's actively writing right
now. Copying a live file with `kubectl cp` is always safe (doesn't touch the source); deleting one
that's still open is not.
