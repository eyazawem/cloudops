#!/usr/bin/env bash
# Restarts RabbitMQ in the Kind cluster and checks that the worker reconnects by itself
# (its restart counter must not change) and that a job submitted afterwards is processed.
set -euo pipefail
ns=cloudops

restart_count() {
  kubectl -n "$ns" get pods -l app=worker -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}'
}
json_field() { python3 -c "import sys, json; print(json.load(sys.stdin)['$1'])"; }

before="$(restart_count)"
echo "worker restarts before: ${before}"

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

echo "== Restarting RabbitMQ =="
kubectl -n "$ns" rollout restart statefulset/rabbitmq
kubectl -n "$ns" rollout status statefulset/rabbitmq --timeout=300s

echo "== Submitting a job after the restart =="
job_id=""
for _ in $(seq 1 12); do
  job_id="$(curl -s -X POST http://127.0.0.1:8000/jobs -H 'Content-Type: application/json' \
    -d '{"task":"report-generation","payload":{"seconds":1}}' | json_field id 2> /dev/null || true)"
  if [ -n "$job_id" ]; then
    break
  fi
  sleep 5
done
[ -n "$job_id" ] || { echo "FAIL: the API could not submit a job"; exit 1; }

status=""
for _ in $(seq 1 120); do
  status="$(curl -s "http://127.0.0.1:8000/jobs/${job_id}" | json_field status)"
  if [ "$status" = "succeeded" ] || [ "$status" = "failed" ]; then
    break
  fi
  sleep 1
done

after="$(restart_count)"
echo "job status: ${status}"
echo "worker restarts after: ${after}"
echo "== Worker log (reconnection) =="
kubectl -n "$ns" logs deployment/worker --tail=-1 | grep -E "RabbitMQ connection|worker started" || true

if [ "$status" = "succeeded" ] && [ "$before" = "$after" ]; then
  echo "PASS: the worker reconnected by itself and processed the job"
else
  echo "FAIL"
  exit 1
fi
