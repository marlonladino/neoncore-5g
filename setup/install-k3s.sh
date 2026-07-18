#!/usr/bin/env bash
# NeonCore 5G — install K3s (single node) using Docker as the container runtime.
# Run this yourself in a terminal with a TTY: bash ~/neoncore-5g/setup/install-k3s.sh
set -euo pipefail

curl -sfL https://get.k3s.io | sh -s - --docker --disable=traefik --disable=servicelb

echo "Waiting for k3s service to be active..."
sudo systemctl is-active --quiet k3s || sudo systemctl start k3s

echo "Waiting for node to register..."
for i in $(seq 1 30); do
  sudo k3s kubectl get nodes 2>/dev/null | grep -q " Ready " && break
  sleep 2
done

mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown "$(id -u):$(id -g)" ~/.kube/config
chmod 600 ~/.kube/config

echo
echo "=== k3s installed ==="
kubectl get nodes -o wide
