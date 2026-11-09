#!/usr/bin/env bash
# Creates or updates the cloudops-secrets Secret from the git-ignored .env file.
set -euo pipefail
root="$(git rev-parse --show-toplevel)"
kubectl --context kind-cloudops -n cloudops create secret generic cloudops-secrets \
  --from-env-file="${root}/.env" --dry-run=client -o yaml \
  | kubectl --context kind-cloudops apply -f -
