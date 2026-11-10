#!/usr/bin/env bash
# Sends requests to the API through its Service while a rolling update runs,
# then reports how many of them failed.
# Usage: bash scripts/k8s-rollout-test.sh [seconds]   (default: 60)
set -euo pipefail
ns=cloudops
duration="${1:-60}"

read -r -d '' loadgen << 'PY' || true
import collections
import os
import time
import urllib.request

duration = float(os.environ["DURATION"])
counts = collections.Counter()
errors = []
for _ in range(60):  # the pod's network may need a moment right after start
    try:
        urllib.request.urlopen("http://api:8000/health", timeout=2).close()
        break
    except Exception:
        time.sleep(0.5)
start = time.monotonic()
while time.monotonic() - start < duration:
    elapsed = time.monotonic() - start
    try:
        with urllib.request.urlopen("http://api:8000/health", timeout=2) as response:
            counts[response.status] += 1
    except Exception as exc:
        counts["error"] += 1
        errors.append((round(elapsed, 1), type(exc).__name__))
    time.sleep(0.05)
print("requests:", sum(counts.values()))
print("results :", dict(counts))
print("errors  :", errors[:20])
PY

kubectl -n "$ns" delete pod loadgen --ignore-not-found --wait=true > /dev/null
kubectl -n "$ns" run loadgen --image=cloudops-api:local --image-pull-policy=IfNotPresent \
  --restart=Never --env="DURATION=${duration}" -- python -c "$loadgen"
kubectl -n "$ns" wait --for=condition=Ready pod/loadgen --timeout=60s

sleep 10
echo "== Rolling update of the API =="
kubectl -n "$ns" rollout restart deployment/api
kubectl -n "$ns" rollout status deployment/api --timeout=180s

echo "== Waiting for the load generator to finish =="
kubectl -n "$ns" wait --for=jsonpath='{.status.phase}'=Succeeded pod/loadgen \
  --timeout="$((duration + 60))s"
kubectl -n "$ns" logs loadgen
kubectl -n "$ns" delete pod loadgen --wait=false > /dev/null
