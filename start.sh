#!/usr/bin/env bash
# Bring the NeonCore 5G stack back up after stop.sh -- starts Docker + K3s, waits
# for the cluster to be ready, scales all workloads back up, and forces a fresh UE
# registration at the end (UPF/SMF/UE pods all get new pod IPs on restart, and SMF
# needs a live UE attach attempt to confirm its PFCP association actually took --
# see DEVLOG.md's WSL-reset-recovery notes for why).
#
# Run this yourself in a normal WSL2 terminal (not through an AI agent): starting
# k3s/docker needs your sudo password and a real TTY, same as the one-time scripts
# in setup/.
set -euo pipefail

echo "==> Starting Docker and K3s (needs your sudo password)..."
sudo systemctl start docker
sudo systemctl start k3s

echo "==> Waiting for the K3s API to come up..."
until kubectl get nodes >/dev/null 2>&1; do
    sleep 2
done
kubectl wait --for=condition=Ready node --all --timeout=120s

echo "==> Scaling neoncore + monitoring workloads back up..."
kubectl -n neoncore scale deployment --all --replicas=1
kubectl -n monitoring scale deployment --all --replicas=1

echo "==> Waiting for pods to become Ready (this can take a minute)..."
# --field-selector excludes dbctl (a one-shot Job pod that's already Succeeded and
# will never satisfy "Ready", which would otherwise drag this out to the full timeout)
kubectl -n neoncore wait --for=condition=Ready pods --all --field-selector=status.phase!=Succeeded --timeout=180s || true
kubectl -n monitoring wait --for=condition=Ready pods --all --timeout=180s || true

echo "==> Forcing a fresh UE registration to confirm everything actually works..."
kubectl -n neoncore delete pod -l app=ue
kubectl -n neoncore wait --for=condition=Ready pod -l app=ue --timeout=60s

echo ""
echo "Current pod status:"
kubectl -n neoncore get pods
kubectl -n monitoring get pods

echo ""
echo "Stack is back up. Sanity check with a ping:"
echo "  UE_POD=\$(kubectl -n neoncore get pods -l app=ue -o jsonpath='{.items[0].metadata.name}')"
echo "  kubectl -n neoncore exec \"\$UE_POD\" -- ping -I uesimtun0 -c 4 8.8.8.8"
