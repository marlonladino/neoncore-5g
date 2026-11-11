#!/usr/bin/env bash
# Pinned Proxmox API helpers. Source it after pin.sh and pin_setup; do not run it.
#   pve_api GET|POST <path> [form-data]   token goes to curl on stdin only, never argv
#   pve_preflight                         /version must answer within 30 s, else abort
#   pve_wait_task <UPID> <seconds>        poll a task until "stopped OK"
# Never use set -x here.
set +x

pve_api() {
    local m="$1" p="$2" d="${3:-}"
    {
        printf '%s\n' "header = \"Authorization: PVEAPIToken=${PVE_API_TOKEN}\"" \
            "url = \"https://${PIN_HOST}:${PIN_PORT}/api2/json${p}\"" \
            "cacert = \"$PIN_LEAF\"" "pinnedpubkey = \"sha256//${PIN_PK}\"" \
            "silent" "show-error" "fail" "max-time = ${PVE_MAX_TIME:-60}" "proto = \"=https\""
        if [ "$m" = POST ]; then printf '%s\n' "request = \"POST\"" "data = \"${d}\""; fi
    } | pin_exec curl --config -
}

# The API hangs while the owner's NAS is off (stuck NFS mount on the host). Stop, do not retry.
pve_preflight() {
    PVE_MAX_TIME=30 pve_api GET /version >/dev/null 2>&1 \
        || pin_die "the Proxmox API did not answer /version within 30 s; stopping (not retrying)"
}

pve_wait_task() {
    local upid="$1" secs="${2:-180}" enc st i
    case "$upid" in UPID:*) ;; *) pin_die "unexpected task id" ;; esac
    enc="$(printf '%s' "$upid" | jq -sRr @uri)"
    for ((i = 0; i < secs; i += 2)); do
        st="$(pve_api GET "/nodes/${TF_VAR_node_name}/tasks/${enc}/status" | jq -r '.data.status + " " + (.data.exitstatus // "")')" || st=""
        case "$st" in
            "stopped OK") return 0 ;;
            stopped*) return 1 ;;
        esac
        sleep 2
    done
    return 2
}

pve_check_vm_env() {
    local v
    for v in PVE_API_TOKEN TF_VAR_node_name TF_VAR_vm_id; do
        [ -n "${!v:-}" ] || pin_die "$v is not set (run through scripts/labenv)"
    done
    case "$TF_VAR_vm_id" in *[!0-9]*|'') pin_die "bad VMID" ;; esac
    case "$TF_VAR_node_name" in *[!A-Za-z0-9.-]*|'') pin_die "bad node name" ;; esac
}
