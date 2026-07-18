#!/bin/bash
# Get the tracer running (no-op if already up) and copy out the newest completed capture.
kubectl -n neoncore scale deployment tracer --replicas=1 >/dev/null
kubectl -n neoncore wait --for=condition=Ready pod -l app=tracer --timeout=60s >/dev/null
TRACER_POD=$(kubectl -n neoncore get pods -l app=tracer -o jsonpath="{.items[0].metadata.name}")
# newest *completed* file = second-newest by name (the newest is likely still open/empty)
LATEST=$(kubectl -n neoncore exec "$TRACER_POD" -- ls -t /pcaps | grep -v "^$" | sed -n "2p")
[ -z "$LATEST" ] && LATEST=$(kubectl -n neoncore exec "$TRACER_POD" -- ls -t /pcaps | head -1)
echo "pulling: $LATEST"
kubectl -n neoncore cp "neoncore/$TRACER_POD:/pcaps/$LATEST" "./$LATEST"

