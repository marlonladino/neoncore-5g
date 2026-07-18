#!/usr/bin/env bash
# Cleanly stop the entire NeonCore 5G stack -- workloads, K3s, and Docker -- to free
# up CPU/RAM in WSL2 when you're not actively testing (e.g. before shutting down
# your PC, or whenever WSL is sitting idle in the background).
#
# Safe: nothing is deleted. Mongo's subscriber data and the tracer's pcap captures
# both live on PVCs (persistent volumes), which survive this untouched -- K3s's own
# cluster state also survives on disk. Run start.sh to bring everything back exactly
# as it was.
#
# Run this yourself in a normal WSL2 terminal (not through an AI agent): stopping
# k3s/docker needs your sudo password and a real TTY, same as the one-time scripts
# in setup/.
set -euo pipefail

echo "==> Scaling down all neoncore + monitoring workloads..."
kubectl -n neoncore scale deployment --all --replicas=0
kubectl -n monitoring scale deployment --all --replicas=0

echo "==> Waiting for pods to terminate..."
for i in $(seq 1 30); do
    n_left=$(kubectl -n neoncore get pods --no-headers 2>/dev/null | grep -vc Completed || true)
    m_left=$(kubectl -n monitoring get pods --no-headers 2>/dev/null | wc -l)
    [ "$n_left" -eq 0 ] && [ "$m_left" -eq 0 ] && break
    sleep 2
done

echo "==> Stopping K3s and Docker (needs your sudo password)..."
sudo systemctl stop k3s
sudo systemctl stop docker

echo ""
echo "Stack fully stopped. WSL2 CPU/RAM usage should now be minimal."
echo "Run ~/neoncore-5g/start.sh to bring everything back up."
