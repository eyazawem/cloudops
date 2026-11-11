#!/usr/bin/env bash
# Installs kubectl 1.34 (to match the cluster) and kind into ~/.local/bin,
# verifying SHA-256 checksums. Make sure ~/.local/bin is on your PATH.
set -euo pipefail

KIND_VERSION="v0.33.0"
mkdir -p ~/.local/bin
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable-1.34.txt)"
case "$KUBECTL_VERSION" in
  v1.34.*) echo "kubectl $KUBECTL_VERSION" ;;
  *) echo "unexpected kubectl version: $KUBECTL_VERSION"; exit 1 ;;
esac
curl -fsSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl"
curl -fsSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl.sha256"
echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check
install -m 0755 kubectl ~/.local/bin/kubectl

curl -fsSLo kind-linux-amd64 "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64"
curl -fsSLo kind-linux-amd64.sha256sum "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-linux-amd64.sha256sum"
sha256sum -c kind-linux-amd64.sha256sum
install -m 0755 kind-linux-amd64 ~/.local/bin/kind

~/.local/bin/kubectl version --client
~/.local/bin/kind version
