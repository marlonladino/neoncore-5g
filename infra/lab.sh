#!/usr/bin/env bash
# NeonCore lab entry point (plan L0, section 4).
#
#   scripts/labenv infra/lab.sh up                       build or converge the whole lab
#   scripts/labenv infra/lab.sh deploy                   workloads: multus, phase2-4, UPF -> SMF -> UE
#   scripts/labenv infra/lab.sh verify                   read-only health check
#   scripts/labenv infra/lab.sh start | stop             VM power plus workloads (recovery order)
#   scripts/labenv infra/lab.sh snapshot <name>          create a snapshot (l0-base, golden-l0, pre-*)
#   scripts/labenv infra/lab.sh status [--selftest-bad-pin]
#
# up, deploy, start, stop and snapshot are mutating: the approval check (lib/approval_check.sh)
# runs before anything else. status and verify are read-only.
# There is NO destroy, rollback or snapshot-delete subcommand; those stay owner-only.
# Never use set -x here; no address, token or fingerprint is printed.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/.." && pwd)"
lib="$here/lib"
# shellcheck source=lib/common.sh
. "$lib/common.sh"

die() { echo "lab.sh: $*" >&2; exit 1; }
usage() {
    cat >&2 <<'EOF'
usage: lab.sh up | deploy | verify | start | stop | snapshot <name> | status [--selftest-bad-pin]
EOF
    exit 2
}

# ---------------------------------------------------------------- argument handling
[ $# -ge 1 ] || usage
sub="$1"; shift
case "$sub" in
    up|deploy|verify|start|stop|status) ;;
    snapshot) ;;
    *) usage ;;
esac
case "$sub" in
    snapshot)
        [ $# -eq 1 ] || usage
        snap="$1"
        case "$snap" in l0-base|golden-l0|pre-*) ;; *) die "snapshot name not allowed (l0-base, golden-l0, pre-*)" ;; esac
        case "$snap" in *[!a-z0-9-]*) die "snapshot name not allowed" ;; esac
        ;;
    status)
        [ $# -le 1 ] || usage
        [ "${1:-}" = "" ] || [ "$1" = "--selftest-bad-pin" ] || usage
        selftest="${1:-}"
        ;;
    *)
        [ $# -eq 0 ] || usage
        ;;
esac

# ---------------------------------------------------------------- approval first
case "$sub" in
    up|deploy|start|stop|snapshot)
        "$lib/approval_check.sh" || die "approval check failed; refusing to $sub"
        ;;
esac

need_env() {
    local v
    for v in PVE_ENDPOINT PVE_API_TOKEN PVE_TLS_FINGERPRINT TF_VAR_node_name TF_VAR_vm_id \
             TF_VAR_ipv4_cidr TF_VAR_vm_user LAB_SSH_KEY_FILE LAB_ADMIN_CIDR; do
        [ -n "${!v:-}" ] || die "$v is not set (run through scripts/labenv)"
    done
    [ -z "${PROXMOX_VE_INSECURE+x}" ] || die "PROXMOX_VE_INSECURE must not be set"
    [ -z "${TF_LOG+x}" ] && [ -z "${TF_LOG_PROVIDER+x}" ] || die "TF_LOG / TF_LOG_PROVIDER must not be set"
    [ -z "$(compgen -v PROXMOX_VE_SSH_)" ] || die "PROXMOX_VE_SSH_* must not be set"
}

step_n=0
step() { step_n=$((step_n + 1)); printf '==> [%s] %s  (%s)\n' "$step_n" "$*" "$(date -u +%H:%M:%SZ)"; }
ns=neoncore

# ---------------------------------------------------------------- cluster helpers
kc() { kubectl "$@"; }

wait_node() {  # wait_node <seconds>
    local i
    for ((i = 0; i < $1; i += 5)); do
        kc get nodes --no-headers 2>/dev/null | grep -q ' Ready ' && return 0
        sleep 5
    done
    return 1
}

# Pods that should be Ready: every pod not owned by a Job, in both namespaces. Prints the bad ones.
not_ready_pods() {
    local n
    for n in neoncore monitoring; do
        kc -n "$n" get pods -o json | jq -r --arg n "$n" '
            .items[] | select(([.metadata.ownerReferences[]?.kind] | index("Job")) | not)
            | select(((.status.phase == "Running") and ([.status.conditions[]? | select(.type=="Ready")][0].status == "True")) | not)
            | $n + "/" + .metadata.name'
    done
}
pod_count() {
    local n
    for n in neoncore monitoring; do kc -n "$n" get pods -o json | jq -r '[.items[]|select(([.metadata.ownerReferences[]?.kind]|index("Job"))|not)]|length'; done | awk '{s+=$1} END{print s+0}'
}

wait_pods_ready() {  # wait_pods_ready <seconds>
    local i bad
    for ((i = 0; i < $1; i += 5)); do
        bad="$(not_ready_pods 2>/dev/null || echo unknown)"
        [ -z "$bad" ] && [ "$(pod_count 2>/dev/null || echo 0)" -gt 0 ] && return 0
        sleep 5
    done
    echo "pods not Ready: $(echo "$bad" | tr '\n' ' ')" >&2
    return 1
}

ue_ping() {  # ue_ping <count>  -> prints "received/sent"
    local out
    out="$(kc -n $ns exec deploy/ue -- ping -I uesimtun0 -c "$1" -W 2 8.8.8.8 2>&1 || true)"
    printf '%s\n' "$out" | sed -n 's/^\([0-9]*\) packets transmitted, \([0-9]*\) \(packets \)\{0,1\}received.*/\2\/\1/p' | head -1
}

wait_ue_tunnel() {
    local i
    for ((i = 0; i < 180; i += 5)); do
        kc -n $ns exec deploy/ue -- ip link show uesimtun0 >/dev/null 2>&1 && return 0
        sleep 5
    done
    return 1
}

upf_counter() {  # upf_counter <metric> -> value or empty; read through the tracer pod (netshoot has curl)
    local ip
    ip="$(kc -n $ns get pod -l app=upf -o jsonpath='{.items[0].status.podIP}' 2>/dev/null)" || return 0
    [ -n "$ip" ] || return 0
    kc -n $ns exec deploy/tracer -- curl -s --max-time 5 "http://$ip:9090/metrics" 2>/dev/null \
        | awk -v m="$1" '$1 == m { print $2; exit }'
}

tracer_newest() {  # "name size" of the newest uncompressed pcap
    kc -n $ns exec deploy/tracer -- sh -c \
        'f=$(ls -t /pcaps 2>/dev/null | grep -v "\.gz$" | head -1); [ -n "$f" ] && echo "$f $(stat -c %s "/pcaps/$f")"' 2>/dev/null || true
}

# Is the newest pcap growing? Traffic is generated through the UE while we watch (up to 60 s).
tracer_growing() {
    local a b i
    a="$(tracer_newest)"; [ -n "$a" ] || return 1
    ( kc -n $ns exec deploy/ue -- ping -I uesimtun0 -c 25 -i 1 -W 2 8.8.8.8 >/dev/null 2>&1 || true ) &
    local bg=$!
    for ((i = 0; i < 60; i += 5)); do
        sleep 5
        b="$(tracer_newest)"
        if [ -n "$b" ] && [ "$b" != "$a" ]; then
            # a different name (rotation) or a larger size both mean tcpdump is writing
            if [ "${b%% *}" != "${a%% *}" ] || [ "${b##* }" -gt "${a##* }" ]; then
                wait "$bg" 2>/dev/null || true; return 0
            fi
        fi
    done
    wait "$bg" 2>/dev/null || true
    return 1
}

# Restart only the tracer pod (never delete a pcap that tcpdump still has open).
tracer_check() {  # tracer_check [restart]
    if tracer_growing; then echo "tracer: newest pcap is growing"; return 0; fi
    if [ "${1:-}" != restart ]; then echo "tracer: newest pcap is NOT growing" >&2; return 1; fi
    echo "tracer: not growing; restarting the tracer pod"
    kc -n $ns rollout restart deploy/tracer >/dev/null
    kc -n $ns rollout status deploy/tracer --timeout=120s >/dev/null
    sleep 10
    if tracer_growing; then echo "tracer: newest pcap is growing after the restart"; return 0; fi
    echo "tracer: still not growing after a restart" >&2
    return 1
}

# Copy tracer files out of the pod into the state dir (outside the repo). The tracer keeps files
# 120 minutes, so only files younger than that exist anyway. Best effort; never deletes anything.
artifacts() {
    local dest n
    dest="$(lab_state)/artifacts/$(date -u +%Y%m%dT%H%M%SZ)"
    mkdir -p "$dest"; chmod 700 "$(lab_state)/artifacts" "$dest"
    if kc -n $ns exec deploy/tracer -- sh -c \
        'cd /pcaps && find . -maxdepth 1 -type f -mmin -120 -name "neoncore-*" | tar -cf - -T -' 2>/dev/null \
        | tar -xf - -C "$dest" 2>/dev/null; then
        n="$(find "$dest" -type f | wc -l)"
        echo "artifacts: copied $n tracer file(s) to the state dir (artifacts/$(basename "$dest"))"
    else
        echo "artifacts: copy failed (tracer not running?)" >&2
    fi
}

# kubectl wait fails at once with "no matching resources found" while the pod does not exist yet
# (right after a scale-up from zero), so retry until a bounded deadline.
wait_pod_ready() {  # wait_pod_ready <label-selector> <seconds>
    local i step="${WAIT_POD_STEP:-3}"
    for ((i = 0; i < $2; i += step)); do
        kc -n $ns wait --for=condition=Ready pod -l "$1" --timeout="${step}s" >/dev/null 2>&1 && return 0
        sleep "$step"
    done
    return 1
}

recover_order() {  # UPF -> SMF -> UE (DEVLOG: SMF caches the old UPF IP)
    echo "recovery order: UPF -> SMF -> UE"
    kc -n $ns rollout status deploy/upf --timeout=300s
    kc -n $ns rollout restart deploy/smf >/dev/null
    kc -n $ns rollout status deploy/smf --timeout=180s
    kc -n $ns rollout restart deploy/ue >/dev/null
    kc -n $ns rollout status deploy/ue --timeout=180s
    wait_ue_tunnel || die "uesimtun0 did not come up"
}

# ---------------------------------------------------------------- subcommands
cmd_deploy() {
    command -v kubectl >/dev/null || die "kubectl not found"
    step "cluster reachable"
    wait_node 180 || die "the K3s node is not Ready"
    step "Multus HelmChart (applied unchanged; the test NAD is never applied)"
    kc apply -f "$repo/phase1/multus-helmchart.yaml"
    local i
    for ((i = 0; i < 300; i += 5)); do
        [ -n "$(kc -n kube-system get pods -l app=rke2-multus -o name 2>/dev/null)" ] && break
        sleep 5
    done
    kc -n kube-system wait --for=condition=Ready pod -l app=rke2-multus --timeout=240s
    step "phase2 base (namespace, configmaps, mongo)"
    local f
    for f in 00-namespace 01-configmaps 02-mongo; do kc apply -f "$repo/phase2/manifests/$f.yaml"; done
    kc -n $ns wait --for=condition=Ready pod -l app=mongo --timeout=180s
    step "phase2 NFs, dbctl, UERANSIM; phase3; phase4"
    for f in "$repo"/phase2/manifests/03-nfs.yaml "$repo"/phase2/manifests/04-dbctl-job.yaml \
             "$repo"/phase2/manifests/05-ueransim.yaml "$repo"/phase3/manifests/*.yaml \
             "$repo"/phase4/manifests/*.yaml; do
        kc apply -f "$f"
    done
    step "recovery order (UPF Ready, then SMF, then UE)"
    recover_order
    step "dbctl Job completes"
    kc -n $ns wait --for=condition=complete job/dbctl --timeout=300s
    step "all workload pods Ready"
    wait_pods_ready 300 || die "pods did not become Ready"
    step "tracer liveness"
    tracer_check restart || die "tracer is not capturing"
    step "copy run artifacts out"
    artifacts
}

# verify: read-only. Prints one line per check; exit 1 if any fails.
cmd_verify() {
    local fails=0
    set +e   # every check is counted, none aborts the script
    chk() { # chk <name> <0|1>
        if [ "$2" = 0 ]; then echo "PASS  $1"; else echo "FAIL  $1"; fails=$((fails + 1)); fi
    }
    command -v kubectl >/dev/null || die "kubectl not found"
    wait_node 30; chk "K3s node Ready" $?
    if [ -n "${TF_VAR_ipv4_cidr:-}" ] && [ -n "${LAB_SSH_KEY_FILE:-}" ] && [ -n "${TF_VAR_vm_user:-}" ]; then
        vm_ssh sudo -n nft list table inet neoncore_guard >/dev/null 2>&1; chk "LAN guard table present on the VM" $?
    else
        echo "FAIL  LAN guard table check needs the lab env (run through scripts/labenv)"; fails=$((fails + 1))
    fi
    local bad
    bad="$(not_ready_pods 2>/dev/null || echo unknown)"
    if [ -z "$bad" ]; then chk "neoncore + monitoring workload pods Ready ($(pod_count 2>/dev/null) pods)" 0
    else chk "workload pods Ready (not ready: $(echo "$bad" | tr '\n' ' '))" 1; fi
    local succ phase
    succ="$(kc -n $ns get job dbctl -o jsonpath='{.status.succeeded}' 2>/dev/null || true)"
    phase="$(kc -n $ns get pods -l job-name=dbctl -o jsonpath='{.items[0].status.phase}' 2>/dev/null || true)"
    [ "$succ" = 1 ] && [ "$phase" = Succeeded ]; chk "dbctl Job Completed (succeeded=${succ:-?}, pod ${phase:-?})" $?
    local before after r
    before="$(upf_counter fivegs_ep_n3_gtp_indatapktn3upf)"
    [ -n "$before" ]; chk "UPF exposes fivegs_ep_n3_gtp_indatapktn3upf" $?
    [ -n "$(upf_counter fivegs_ep_n3_gtp_outdatapktn3upf)" ]; chk "UPF exposes fivegs_ep_n3_gtp_outdatapktn3upf" $?
    r="$(ue_ping 5)"
    [ -n "$r" ] && [ "${r%/*}" -ge 4 ]; chk "UE ping via uesimtun0 to 8.8.8.8 (${r:-no result} received/sent)" $?
    after="$(upf_counter fivegs_ep_n3_gtp_indatapktn3upf)"
    [ -n "$before" ] && [ -n "$after" ] && awk -v a="$before" -v b="$after" 'BEGIN{exit !(b>a)}'; chk "N3 GTP in-counter rose during the ping (${before:-?} -> ${after:-?})" $?
    tracer_check; chk "tracer newest pcap growing" $?
    [ "$fails" = 0 ] || { echo "verify: $fails check(s) failed" >&2; exit 1; }
    echo "verify: all checks passed"
}

cmd_status() {
    if [ "$selftest" = "--selftest-bad-pin" ]; then
        # Fail-only (E10): the flag flips one digit of the expected pin. Nothing else runs.
        "$lib/pin_check.sh" --selftest-bad-pin && die "selftest unexpectedly passed"
        exit 1
    fi
    need_env
    "$lib/pin_check.sh"
    timeout 60 "$lib/pve_power.sh" status || echo "vm: status unavailable"
    if command -v kubectl >/dev/null && timeout 15 kubectl get nodes --no-headers >/dev/null 2>&1; then
        echo "k3s node: $(kubectl get nodes --no-headers | awk '{print $2}' | head -1)"
        local n
        for n in neoncore monitoring; do
            echo "pods $n: $(kubectl -n "$n" get pods --no-headers 2>/dev/null | awk '{c[$3]++} END{for(k in c) printf "%s=%d ", k, c[k]}')"
        done
    else
        echo "k3s: not reachable"
    fi
}

cmd_snapshot() { need_env; "$lib/pve_snapshot.sh" create "$snap"; }

cmd_start() {
    need_env
    step "pin check"; "$lib/pin_check.sh"
    step "VM power on"; "$lib/pve_power.sh" start
    step "SSH (strict host key)"; wait_ssh 300 || die "VM did not accept SSH within 300 s"
    step "K3s node Ready"; wait_node 300 || die "the K3s node is not Ready"
    step "scale workloads up"
    kc -n monitoring scale deployment --all --replicas=1
    kc -n $ns scale deployment --all --replicas=1
    wait_pod_ready app=upf 300 || die "UPF pod did not become Ready within 300 s"
    step "recovery order after boot (pod IPs can change)"
    recover_order
    step "all workload pods Ready"; wait_pods_ready 300 || die "pods did not become Ready"
    step "tracer liveness"; tracer_check restart || die "tracer is not capturing"
    kc -n $ns get pods; kc -n monitoring get pods
}

cmd_stop() {
    need_env
    step "pin check"; "$lib/pin_check.sh"
    if kc get nodes >/dev/null 2>&1; then
        step "copy run artifacts out"; artifacts
        step "scale workloads down"
        kc -n $ns scale deployment --all --replicas=0
        kc -n monitoring scale deployment --all --replicas=0
        local i left
        for ((i = 0; i < 90; i += 3)); do
            left="$(kc -n $ns get pods --no-headers 2>/dev/null | grep -vc Completed || true)"
            left=$((left + $(kc -n monitoring get pods --no-headers 2>/dev/null | wc -l)))
            [ "$left" -eq 0 ] && break
            sleep 3
        done
    else
        echo "cluster not reachable; going straight to VM shutdown"
    fi
    step "VM graceful shutdown"; "$lib/pve_power.sh" shutdown
}

cmd_up() {
    need_env
    local fresh=0 out planfile
    step "pin check"; "$lib/pin_check.sh"
    step "terraform init and plan (plan guard, fail-closed)"
    "$lib/tf.sh" init >/dev/null
    out="$("$lib/tf.sh" plan)" || { echo "$out" >&2; die "plan refused by the guard; stopping"; }
    echo "$out"
    planfile="$(printf '%s\n' "$out" | sed -n 's/^plan file: //p' | head -1)"
    [ -n "$planfile" ] || die "no plan file reported"
    printf '%s\n' "$out" | grep -q '^summary:.*create' && fresh=1
    step "terraform apply of the saved plan"
    "$lib/tf.sh" apply "$planfile"
    step "VM running"; "$lib/pve_power.sh" start
    step "cloud-init wait and SSH host key pin"
    if [ "$fresh" = 1 ]; then "$lib/hostkey.sh" --fresh; else "$lib/hostkey.sh"; fi
    wait_ssh 300 || die "VM did not accept SSH within 300 s"
    local rc=0
    vm_ssh cloud-init status --wait >/dev/null 2>&1 || rc=$?
    # 0 = done, 2 = done with recoverable errors (the template's deprecation warnings)
    case "$rc" in 0|2) ;; *) die "cloud-init did not finish cleanly (exit $rc)" ;; esac
    step "Ansible: base, kernel, docker, firewall"; "$lib/ansible.sh" site.yml
    step "Ansible: K3s, kubeconfig, UPF image"; "$lib/ansible.sh" k3s.yml
    step "deploy"; cmd_deploy
    step "verify"; cmd_verify
    echo "lab.sh up: done"
}

case "$sub" in
    up) cmd_up ;;
    deploy) cmd_deploy ;;
    verify) cmd_verify ;;
    start) cmd_start ;;
    stop) cmd_stop ;;
    snapshot) cmd_snapshot ;;
    status) cmd_status ;;
esac
