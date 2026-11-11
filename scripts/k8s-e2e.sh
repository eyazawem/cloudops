#!/usr/bin/env bash
# Runs the integration tests against the Kind cluster through kubectl port-forward.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"

if ss -ltn | grep -qE ':(8000|15672)\b'; then
  echo "Port 8000 or 15672 is already in use: stop what uses it (e.g. docker compose down)."
  exit 1
fi

ctx=kind-cloudops
kubectl --context "$ctx" -n cloudops port-forward svc/api 8000:8000 > /tmp/pf-api.log 2>&1 &
pf_api=$!
kubectl --context "$ctx" -n cloudops port-forward pod/rabbitmq-0 15672:15672 > /tmp/pf-rabbitmq.log 2>&1 &
pf_mq=$!
trap 'kill "$pf_api" "$pf_mq" 2>/dev/null || true' EXIT

if [ -z "${VIRTUAL_ENV:-}" ] && [ -f "${root}/services/api/.venv/bin/activate" ]; then
  source "${root}/services/api/.venv/bin/activate"
fi
source "${root}/scripts/dev-env.sh"
cd "${root}/services/api"
python -m pytest integration_tests -v
