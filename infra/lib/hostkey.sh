#!/usr/bin/env bash
# Pin the VM's SSH host key into the dedicated known_hosts (security review S-B6).
#   scripts/labenv infra/lib/hostkey.sh [--fresh]
# Order: (1) A12: read /etc/ssh/ssh_host_ed25519_key.pub through the pinned, authenticated API
# (guest agent file-read); with an existing entry it only COMPARES and aborts on a mismatch. (2) D17 fallback (owner-accepted): trust on first use with
# StrictHostKeyChecking=accept-new into the dedicated file, and only when there is no entry yet or
# --fresh says this run just created the VM. Without --fresh an existing entry is only verified
# (strict); a mismatch is never replaced silently. Mutating, so the approval check runs first.
# Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pin.sh"
. "$here/pve_api.sh"
. "$here/common.sh"

fresh=0
case "${1:-}" in "") ;; --fresh) fresh=1 ;; *) pin_die "usage: hostkey.sh [--fresh]" ;; esac
for v in TF_VAR_ipv4_cidr TF_VAR_vm_user LAB_SSH_KEY_FILE; do
    [ -n "${!v:-}" ] || pin_die "$v is not set (run through scripts/labenv)"
done
pve_check_vm_env
"$here/approval_check.sh" || pin_die "approval check failed"

state="$(lab_state)"; mkdir -p "$state"; chmod 700 "$state"
kh="$state/known_hosts"; touch "$kh"; chmod 600 "$kh"
ip="$(lab_ip)"

have_entry() { ssh-keygen -F "$ip" -f "$kh" >/dev/null 2>&1; }

pin_setup
pve_preflight
# --fresh: this run just created the VM, so an older entry belongs to a previous VM.
if [ "$fresh" = 1 ]; then
    ssh-keygen -R "$ip" -f "$kh" >/dev/null 2>&1 || true
    rm -f "$kh.old"
fi
# (1) guest-agent read
pub=""
enc="$(printf '%s' /etc/ssh/ssh_host_ed25519_key.pub | jq -sRr @uri)"
if pub="$(PVE_MAX_TIME=30 pve_api GET "/nodes/${TF_VAR_node_name}/qemu/${TF_VAR_vm_id}/agent/file-read?file=${enc}" 2>/dev/null | jq -r '.data.content // empty')" \
   && [ -n "$pub" ]; then
    set -- $pub
    [ "${1:-}" = ssh-ed25519 ] && [ -n "${2:-}" ] || pin_die "unexpected host key format from the guest agent"
    if have_entry; then
        # An entry exists (e.g. D17 TOFU): compare, never replace. A mismatch aborts.
        if ssh-keygen -F "$ip" -f "$kh" 2>/dev/null | awk -v t="$1" -v k="$2" '$1 !~ /^#/ && $2 == t && $3 == k {f=1} END {exit !f}'; then
            echo "hostkey: existing pin matches the guest-agent key (authenticated API)"
            exit 0
        fi
        pin_die "host key mismatch: the pinned key differs from the guest-agent key; not replacing it"
    fi
    printf '%s %s %s\n' "$ip" "$1" "$2" >>"$kh"
    echo "hostkey: pinned from the guest agent (authenticated API)"
    exit 0
fi

# (2) D17 fallback
if have_entry && [ "$fresh" = 0 ]; then
    vm_ssh true >/dev/null 2>&1 || pin_die "host key mismatch or VM unreachable; not replacing the pinned key"
    echo "hostkey: existing pin verified (strict)"
    exit 0
fi
if [ "$fresh" = 1 ]; then
    ssh-keygen -R "$ip" -f "$kh" >/dev/null 2>&1 || true
    rm -f "$kh.old"
fi
wait_ssh 300 --accept-new || pin_die "VM did not accept SSH within 300 s"
vm_ssh true >/dev/null 2>&1 || pin_die "strict check failed after pinning"
echo "hostkey: pinned by trust on first use (D17), strict checking from now on"
