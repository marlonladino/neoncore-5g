#!/usr/bin/env bash
# Start the NeonCore lab: thin wrapper over infra/lab.sh start.
#
# On Proxmox this powers the VM on through the API and scales the workloads up, then recovers in
# the order UPF -> SMF -> UE (DEVLOG: pod IPs can change on boot, SMF caches the old UPF IP) and
# checks that the tracer's newest pcap is growing. The approval check runs first; the one
# exemption is the owner at a real terminal outside Claude Code (see infra/lib/approval_check.sh).
# Run it as: ./start.sh
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$repo/infra/lib/approval_check.sh"
exec "$repo/scripts/labenv" "$repo/infra/lab.sh" start
