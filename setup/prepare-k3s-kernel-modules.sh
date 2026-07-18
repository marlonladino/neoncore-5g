#!/usr/bin/env bash
# NeonCore 5G — kernel module prerequisites for K3s + Multus (macvlan/ipvlan).
# Run this yourself in a terminal with a TTY: bash ~/neoncore-5g/setup/prepare-k3s-kernel-modules.sh
set -euo pipefail

for mod in iptable_nat macvlan ipvlan; do
  sudo modprobe "$mod"
  lsmod | grep -q "^${mod}" && echo "$mod: loaded OK"
done

echo -e "iptable_nat\nmacvlan\nipvlan" | sudo tee /etc/modules-load.d/neoncore-k3s.conf > /dev/null
echo "Persisted: iptable_nat, macvlan, ipvlan will auto-load on future WSL2 boots"
