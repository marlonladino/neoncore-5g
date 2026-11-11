#!/usr/bin/env bash
# TB6 / plan section 8.6 and B5: record interface MTUs, informational, no threshold.
#
#   evals/l0/mtu_check.sh --out-dir DIR [--label TEXT]   pod side, via kubectl (read-only)
#   evals/l0/mtu_check.sh --node                         node side, run ON the lab VM by lab-ops
#   evals/l0/mtu_check.sh --print-node-commands          the exact node commands for lab-ops
#   evals/l0/mtu_check.sh --lines [--label TEXT]         pod lines to stdout, unredacted, for a
#                                                        caller that pipes them into redact.py
#                                                        (capture_baseline.sh versions does)
#
# Pod side reads `ip -o link show` in the gnb, upf (container upf) and ue pods:
#   eth0 in gnb/upf/ue, ogstun in upf, uesimtun0 in ue.
# Node side (VM NIC = the default-route device, flannel.1, cni0) needs a shell on the VM,
# which only lab-ops has; the evaluator prints the commands and records "not captured".
# The path-MTU ping (`ping -M do -s 1372 -I uesimtun0 -c 3 -W 2 8.8.8.8`) is not run
# here: it goes through ping_check.sh --pmtu (the existing ping path).
# Writes DIR/mtu.txt through redact.py (text). Exit: 0 written, 2 usage error.
set -uo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out_dir="" label="informational" mode="pods"
while [ $# -gt 0 ]; do
    case "$1" in
        --out-dir) out_dir="$2"; shift 2 ;;
        --label) label="$2"; shift 2 ;;
        --node) mode="node"; shift ;;
        --print-node-commands) mode="print"; shift ;;
        --lines) mode="lines"; shift ;;
        *) echo "mtu_check: unknown argument" >&2; exit 2 ;;
    esac
done
[[ "$label" =~ ^[A-Za-z0-9\ ._-]{1,60}$ ]] || { echo "mtu_check: bad --label" >&2; exit 2; }

# One line per command; test_shell.py runs NODE_CMDS locally against a fake /sys.
NODE_CMDS='dev="$(ip -o route show default 2>/dev/null | awk '"'"'{for(i=1;i<NF;i++) if($i=="dev"){print $(i+1); exit}}'"'"')"; echo "mtu_vm_nic ($dev): $(cat "${SYSFS:-/sys}/class/net/$dev/mtu" 2>/dev/null || echo unavailable)"; for i in flannel.1 cni0; do echo "mtu_$i: $(cat "${SYSFS:-/sys}/class/net/$i/mtu" 2>/dev/null || echo absent)"; done'

if [ "$mode" = print ]; then
    echo "# Run on the lab VM as lab-ops (read-only), paste the 3 output lines back:"
    printf '%s\n' "$NODE_CMDS"
    echo "# Proxmox bridge MTU and VLAN tag: owner or lab-ops on the Proxmox host (not via the VM):"
    echo "#   ip -d link show <bridge from the site config>   (report mtu and any vlan id; do not commit the bridge name)"
    exit 0
fi
if [ "$mode" = node ]; then
    sh -c "$NODE_CMDS"
    exit 0
fi
[ "$mode" = lines ] || [ -n "$out_dir" ] || { echo "usage: mtu_check.sh --out-dir DIR [--label TEXT]" >&2; exit 2; }
nosite=""   # tests only: synthetic data, no site value can occur
[ "${L0_ALLOW_NO_SITE_VALUES:-}" = 1 ] && nosite=1

# parse_mtu IFNAME < `ip -o link show` output -> MTU number or "absent"
parse_mtu() {
    awk -v want="$1" '{
        n = $2; sub(/:$/, "", n); sub(/@.*/, "", n)
        if (n == want) { for (i = 3; i < NF; i++) if ($i == "mtu") { print $(i+1); found = 1; exit } }
    } END { if (!found) print "absent" }'
}

pod_links() {  # $1 deploy, $2 container or ""
    local c=()
    [ -n "$2" ] && c=(-c "$2")
    timeout 30 kubectl -n neoncore exec "deploy/$1" "${c[@]}" -- ip -o link show 2>/dev/null
}

lines() {
    echo "mtu_label: $label"
    echo "mtu_captured_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "mtu_source_pods: kubectl -n neoncore exec deploy/<pod> -- ip -o link show"
    gnb="$(pod_links gnb "")"; upf="$(pod_links upf upf)"; ue="$(pod_links ue "")"
    for spec in "gnb eth0" "upf eth0" "upf ogstun" "ue eth0" "ue uesimtun0"; do
        set -- $spec
        case "$1" in gnb) txt="$gnb" ;; upf) txt="$upf" ;; ue) txt="$ue" ;; esac
        if [ -z "$txt" ]; then v="unavailable (exec failed)"; else v="$(printf '%s\n' "$txt" | parse_mtu "$2")"; fi
        echo "mtu_pod_$1_$2: $v"
        [ "$1/$2" = "ue/uesimtun0" ] && ue_mtu="$v"
    done
    if [[ "${ue_mtu:-}" =~ ^[0-9]+$ ]] && [ "$ue_mtu" != 1400 ]; then
        echo "note_uesimtun0: $ue_mtu, not the SMF mtu 1400; the PDU session establishment accept carries no IPv4 Link MTU ePCO container (telco build review R1, MTU point), so the SMF value is not conveyed to the UE"
    fi
    echo "mtu_vm_nic: not captured (needs a shell on the VM; lab-ops runs: evals/l0/mtu_check.sh --print-node-commands)"
    echo "mtu_flannel.1: not captured (lab-ops, as above)"
    echo "mtu_cni0: not captured (lab-ops, as above)"
    echo "mtu_proxmox_bridge: not captured (owner or lab-ops on the Proxmox host)"
    echo "pmtu_note: the 1372-byte DF ping is not run by mtu_check.sh (ping_check.sh --pmtu, informational, no threshold)"
}
if [ "$mode" = lines ]; then
    lines
    exit 0
fi
mkdir -p "$out_dir"
lines | python3 -I "$here/redact.py" ${nosite:+--allow-no-site-values} --format text -o "$out_dir/mtu.txt"
rc=${PIPESTATUS[1]}
[ "$rc" = 0 ] && cat "$out_dir/mtu.txt"
exit "$rc"
