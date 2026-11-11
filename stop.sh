#!/usr/bin/env bash
# Stop the NeonCore lab cleanly: thin wrapper over infra/lab.sh stop.
#
# Copies the tracer's recent pcaps out (2 h retention), scales all workloads to zero, then asks the
# VM for a graceful shutdown through the API. Nothing is deleted: Mongo and the pcap PVC survive,
# and ./start.sh brings everything back. The approval check runs first; the one exemption is the
# owner at a real terminal outside Claude Code (see infra/lib/approval_check.sh).
# Run it as: ./stop.sh
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$repo/infra/lib/approval_check.sh"
exec "$repo/scripts/labenv" "$repo/infra/lab.sh" stop
