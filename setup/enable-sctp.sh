#!/usr/bin/env bash
# NeonCore 5G — load the SCTP kernel module (required for AMF N2/NGAP) and make it persistent
# across WSL2 restarts. Run this yourself in a terminal with a TTY:
#   bash ~/neoncore-5g/setup/enable-sctp.sh
set -euo pipefail

sudo modprobe sctp
lsmod | grep -q '^sctp' && echo "sctp module loaded OK"

echo "sctp" | sudo tee /etc/modules-load.d/sctp.conf > /dev/null
echo "Persisted: sctp will auto-load on future WSL2 boots (/etc/modules-load.d/sctp.conf)"
