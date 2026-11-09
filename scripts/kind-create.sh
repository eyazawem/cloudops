#!/usr/bin/env bash
# Creates the local Kind cluster "cloudops" with a pinned node image.
# The image is Kubernetes 1.34 because newer kubelets refuse to start on hosts
# using cgroup v1 (check with: stat -fc %T /sys/fs/cgroup/ -> tmpfs = v1).
set -euo pipefail

if kind get clusters | grep -qx cloudops; then
  echo "Cluster cloudops already exists."
  exit 0
fi

avail_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
echo "Available memory: $((avail_kb / 1024)) MB"
if [ "$avail_kb" -lt 3145728 ]; then
  echo "Less than 3 GiB available: close some applications and retry."
  exit 1
fi

kind create cluster --name cloudops \
  --image kindest/node:v1.34.11@sha256:44e222ee2132dab25ff87301682f89eb82c7880ea3a1bf543bfe9708fd08d67d
