#!/usr/bin/env bash
# Installs metrics-server, creates the API's HPA, generates load from inside the
# cluster and prints how the autoscaler reacts (scale up, then scale down).
# Usage: bash scripts/k8s-hpa-demo.sh [load_seconds] [threads]   (defaults: 150, 8)
set -euo pipefail
ns=cloudops
load="${1:-150}"
threads="${2:-8}"
root="$(git rev-parse --show-toplevel)"

bash "${root}/scripts/k8s-install-metrics-server.sh"
kubectl apply -f "${root}/deploy/k8s/60-api-hpa.yaml"

read -r -d '' loadgen << 'PY' || true
import os
import threading
import time
import urllib.request

duration = float(os.environ["DURATION"])
threads = int(os.environ["THREADS"])
deadline = time.monotonic() + duration
lock = threading.Lock()
totals = {"ok": 0, "error": 0}


def hammer():
    ok = error = 0
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen("http://api:8000/health", timeout=2).close()
            ok += 1
        except Exception:
            error += 1
    with lock:
        totals["ok"] += ok
        totals["error"] += error


pool = [threading.Thread(target=hammer) for _ in range(threads)]
for t in pool:
    t.start()
for t in pool:
    t.join()
print("requests:", totals)
PY

snapshot() {
  printf '%s  ' "$(date +%T)"
  kubectl -n "$ns" get hpa api -o jsonpath='cpu={.status.currentMetrics[0].resource.current.averageUtilization}% (target 50%)  replicas={.status.currentReplicas}  desired={.status.desiredReplicas}' || true
  echo
}

echo "== Waiting for the first CPU measurement =="
for _ in $(seq 1 30); do
  value="$(kubectl -n "$ns" get hpa api -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || true)"
  if [ -n "$value" ]; then
    break
  fi
  sleep 5
done

echo "== Before the load =="
snapshot

kubectl -n "$ns" delete pod loadgen-hpa --ignore-not-found --wait=true > /dev/null
kubectl -n "$ns" run loadgen-hpa --image=cloudops-api:local --image-pull-policy=IfNotPresent \
  --restart=Never --env="DURATION=${load}" --env="THREADS=${threads}" -- python -c "$loadgen"

echo "== During the load (${load} s) and after it =="
total=$((load + 180))
elapsed=0
while [ "$elapsed" -lt "$total" ]; do
  snapshot
  sleep 10
  elapsed=$((elapsed + 10))
done

echo "== Load generator report =="
kubectl -n "$ns" logs loadgen-hpa || true
kubectl -n "$ns" delete pod loadgen-hpa --wait=false > /dev/null
kubectl -n "$ns" get hpa api
kubectl -n "$ns" get pods -l app=api
