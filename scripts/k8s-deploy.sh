#!/usr/bin/env bash
# Builds the API image, loads it into the Kind cluster and deploys everything.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
cd "$root"

if [ "$(kubectl config current-context)" != "kind-cloudops" ]; then
  echo "Unexpected kubectl context: $(kubectl config current-context)"
  exit 1
fi

docker build -t cloudops-api:local services/api
# Public images are loaded from the local Docker cache to avoid downloading them
# again inside the cluster. CI sets LOAD_PUBLIC_IMAGES=false: the cluster pulls them.
if [ "${LOAD_PUBLIC_IMAGES:-true}" = "true" ]; then
  for image in postgres:17 rabbitmq:4-management; do
    docker image inspect "$image" > /dev/null 2>&1 || docker pull "$image"
  done
  kind load docker-image postgres:17 rabbitmq:4-management --name cloudops
fi
kind load docker-image cloudops-api:local --name cloudops

kubectl apply -f deploy/k8s/00-namespace.yaml
bash scripts/k8s-secrets.sh
kubectl apply -f deploy/k8s/10-postgres.yaml -f deploy/k8s/20-rabbitmq.yaml
kubectl -n cloudops rollout status statefulset/postgres --timeout=300s
kubectl -n cloudops rollout status statefulset/rabbitmq --timeout=300s

# A Job's pod template is immutable: recreate it on every deployment.
kubectl -n cloudops delete job migrate --ignore-not-found
kubectl apply -f deploy/k8s/30-migrate.yaml
kubectl -n cloudops wait --for=condition=complete job/migrate --timeout=300s

kubectl apply -f deploy/k8s/40-api.yaml -f deploy/k8s/50-worker.yaml
kubectl -n cloudops rollout status deployment/api --timeout=300s
kubectl -n cloudops rollout status deployment/worker --timeout=300s
kubectl -n cloudops get pods,svc
