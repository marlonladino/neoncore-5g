#!/usr/bin/env bash
# Power state of the NeonCore VM through the pinned API: status | start | shutdown.
#   scripts/labenv infra/lib/pve_power.sh status
# status is read-only. start and shutdown run the approval check first. Only this VM
# (TF_VAR_vm_id on TF_VAR_node_name); no stop/reset/destroy: shutdown is a graceful ACPI request.
# Never use set -x here.
set -euo pipefail
set +x
umask 077
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/pin.sh"
. "$here/pve_api.sh"

[ $# -eq 1 ] || pin_die "usage: pve_power.sh status|start|shutdown"
act="$1"
case "$act" in status|start|shutdown) ;; *) pin_die "usage: pve_power.sh status|start|shutdown" ;; esac
pve_check_vm_env
[ "$act" = status ] || "$here/approval_check.sh" || pin_die "approval check failed"
pin_setup
pve_preflight

base="/nodes/${TF_VAR_node_name}/qemu/${TF_VAR_vm_id}/status"
cur() { pve_api GET "$base/current" | jq -r '.data.status'; }
st="$(cur)"
case "$act" in
status) echo "vm: $st" ;;
start)
    [ "$st" != running ] || { echo "vm: already running"; exit 0; }
    upid="$(pve_api POST "$base/start" "" | jq -r '.data')"
    pve_wait_task "$upid" 120 || pin_die "start task did not finish OK"
    echo "vm: started"
    ;;
shutdown)
    [ "$st" != stopped ] || { echo "vm: already stopped"; exit 0; }
    upid="$(pve_api POST "$base/shutdown" "timeout=180" | jq -r '.data')"
    pve_wait_task "$upid" 240 || pin_die "shutdown task did not finish OK"
    [ "$(cur)" = stopped ] || pin_die "vm did not stop"
    echo "vm: stopped"
    ;;
esac
