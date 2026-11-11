#!/usr/bin/env bash
# Shared helpers for SSH to the lab VM with strict host-key checking against the dedicated
# known_hosts. Source it; do not run it. No address is printed. Never use set -x here.
set +x

lab_state() { printf '%s' "${NEONCORE_STATE_DIR:-$HOME/.local/state/neoncore}"; }
lab_ip() { printf '%s' "${TF_VAR_ipv4_cidr%/*}"; }

# vm_ssh [--accept-new] <command...>
vm_ssh() {
    local policy=yes
    if [ "${1:-}" = "--accept-new" ]; then policy=accept-new; shift; fi
    ssh -i "$LAB_SSH_KEY_FILE" -o IdentitiesOnly=yes -o BatchMode=yes \
        -o StrictHostKeyChecking="$policy" -o UserKnownHostsFile="$(lab_state)/known_hosts" \
        -o ConnectTimeout=10 "${TF_VAR_vm_user}@$(lab_ip)" "$@"
}

# wait_ssh <seconds> [--accept-new]
wait_ssh() {
    local secs="$1"; shift
    local i
    for ((i = 0; i < secs; i += 5)); do
        vm_ssh "$@" true >/dev/null 2>&1 && return 0
        sleep 5
    done
    return 1
}
