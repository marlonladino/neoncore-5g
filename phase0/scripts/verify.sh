#!/usr/bin/env bash
# Phase 0 success-criteria check for NeonCore 5G.
set -uo pipefail
cd "$(dirname "$0")/.."

echo "=== docker compose ps ==="
docker compose ps
echo

echo "=== NF health (all should be Up, no restarts) ==="
for svc in nrf ausf udm udr pcf amf smf upf; do
  status=$(docker inspect -f '{{.State.Status}} restarts={{.RestartCount}}' "$svc" 2>&1)
  echo "$svc: $status"
done
echo

echo "=== AMF: gNB NG Setup ==="
docker logs amf 2>&1 | grep -iE "ng setup|gnb_name|nssai" | tail -20
echo

echo "=== gNB: AMF connection ==="
docker logs gnb 2>&1 | grep -iE "ngap|amf" | tail -20
echo

echo "=== UE: registration / PDU session ==="
docker logs ue 2>&1 | tail -40
echo

echo "=== uesimtun0 interface (inside ue container) ==="
docker exec ue ip addr show uesimtun0
echo

echo "=== Ping test through the tunnel (uesimtun0 -> 8.8.8.8) ==="
docker exec ue ping -I uesimtun0 -c 4 8.8.8.8
