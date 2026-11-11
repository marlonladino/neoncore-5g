#!/usr/bin/env bash
# Create a VM snapshot through the pinned API (a create, never a rollback or delete).
#   scripts/labenv infra/lib/pve_snapshot.sh create <name>
# Mutating: runs the approval check first. Token goes to curl on stdin only.
# Only POST to .../snapshot; no rollback, no delete. Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pin.sh"

[ $# -eq 2 ] && [ "$1" = create ] || pin_die "usage: pve_snapshot.sh create <name>"
name="$2"
case "$name" in l0-base|golden-l0|pre-*) ;; *) pin_die "snapshot name not allowed" ;; esac
case "$name" in *[!a-z0-9-]*) pin_die "snapshot name not allowed" ;; esac
for v in PVE_API_TOKEN TF_VAR_node_name TF_VAR_vm_id; do
    [ -n "${!v:-}" ] || pin_die "$v is not set (run through scripts/labenv)"
done
case "$TF_VAR_vm_id" in *[!0-9]*|'') pin_die "bad VMID" ;; esac
case "$TF_VAR_node_name" in *[!A-Za-z0-9.-]*|'') pin_die "bad node name" ;; esac
"$here/approval_check.sh" || pin_die "approval check failed"
pin_setup

api() {  # api GET|POST <path> [form-data]
    local m="$1" p="$2" d="${3:-}"
    {
        printf '%s\n' "header = \"Authorization: PVEAPIToken=${PVE_API_TOKEN}\"" \
            "url = \"https://${PIN_HOST}:${PIN_PORT}/api2/json${p}\"" \
            "cacert = \"$PIN_LEAF\"" "pinnedpubkey = \"sha256//${PIN_PK}\"" \
            "silent" "show-error" "fail" "max-time = 60" "proto = \"=https\""
        if [ "$m" = POST ]; then printf '%s\n' "request = \"POST\"" "data = \"${d}\""; fi
    } | pin_exec curl --config -
}

base="/nodes/${TF_VAR_node_name}/qemu/${TF_VAR_vm_id}/snapshot"
if api GET "$base" | jq -e --arg n "$name" '.data[]|select(.name==$n)' >/dev/null; then
    echo "snapshot $name already exists"; exit 0
fi
upid="$(api POST "$base" "snapname=${name}&description=NeonCore+L0" | jq -r '.data')"
case "$upid" in UPID:*) ;; *) pin_die "unexpected snapshot response" ;; esac
enc="$(printf '%s' "$upid" | jq -sRr @uri)"
for _ in $(seq 1 90); do
    st="$(api GET "/nodes/${TF_VAR_node_name}/tasks/${enc}/status" | jq -r '.data.status + " " + (.data.exitstatus // "")')"
    case "$st" in
        "stopped OK") echo "snapshot $name created"; exit 0 ;;
        stopped*) pin_die "snapshot task failed" ;;
    esac
    sleep 2
done
pin_die "snapshot task did not finish in time"
