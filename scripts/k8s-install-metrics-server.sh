#!/usr/bin/env bash
# Installs metrics-server (pinned version) in the Kind cluster.
# Kind's kubelet serves self-signed certificates, hence --kubelet-insecure-tls:
# acceptable for a local development cluster only, never for production.
set -euo pipefail
VERSION="v0.9.1"

kubectl apply -f "https://github.com/kubernetes-sigs/metrics-server/releases/download/${VERSION}/components.yaml"

args="$(kubectl -n kube-system get deployment metrics-server -o jsonpath='{.spec.template.spec.containers[0].args}')"
if ! printf '%s' "$args" | grep -q -- '--kubelet-insecure-tls'; then
  kubectl -n kube-system patch deployment metrics-server --type=json \
    -p '[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]'
fi
kubectl -n kube-system rollout status deployment/metrics-server --timeout=180s

for _ in $(seq 1 36); do
  if kubectl top nodes > /dev/null 2>&1; then
    break
  fi
  sleep 5
done
kubectl top nodes
