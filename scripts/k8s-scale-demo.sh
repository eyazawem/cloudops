#!/usr/bin/env bash
# Compares the time needed to process 12 jobs of 3 s with 1 worker, then 3 workers.
set -euo pipefail
ns=cloudops
count=12

kubectl -n "$ns" port-forward svc/api 8000:8000 > /tmp/pf-api.log 2>&1 &
pf=$!
trap 'kill "$pf" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:8000/health > /dev/null

json_field() { python3 -c "import sys, json; print(json.load(sys.stdin)['$1'])"; }

run_batch() {
  local replicas="$1"
  local ids=()
  kubectl -n "$ns" scale deployment/worker --replicas="$replicas" > /dev/null
  kubectl -n "$ns" rollout status deployment/worker --timeout=120s > /dev/null
  sleep 5
  local t0=$SECONDS
  local start
  start=$(date +%s.%N)
  for _ in $(seq 1 "$count"); do
    ids+=("$(curl -s -X POST http://127.0.0.1:8000/jobs \
      -H "Content-Type: application/json" \
      -d '{"task":"report-generation","payload":{"seconds":3}}' | json_field id)")
  done
  local deadline=$((SECONDS + 120))
  for id in "${ids[@]}"; do
    until [ "$(curl -s "http://127.0.0.1:8000/jobs/$id" | json_field status)" = "succeeded" ]; do
      if [ "$SECONDS" -ge "$deadline" ]; then
        echo "timeout waiting for job $id"
        return 1
      fi
      sleep 0.5
    done
  done
  local end
  end=$(date +%s.%N)
  python3 -c "print('${replicas} worker(s): ${count} jobs of 3 s processed in {:.1f} s'.format($end - $start))"
  echo "jobs per worker pod:"
  kubectl -n "$ns" logs -l app=worker --prefix --tail=-1 --since="$((SECONDS - t0 + 2))s" \
    | grep "running (task=report-generation" | awk '{print $1}' | sort | uniq -c
}

echo "== 1 worker =="
run_batch 1
echo "== 3 workers =="
run_batch 3
kubectl -n "$ns" scale deployment/worker --replicas=1 > /dev/null
echo "== Back to 1 worker =="
