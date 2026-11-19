#!/usr/bin/env bash
# Installs a pinned Trivy release into ~/.local/bin, verifying SHA-256 checksums.
# The binary is installed directly instead of using a third-party GitHub Action:
# in March 2026 a Trivy release and the Trivy GitHub Actions were compromised
# (GHSA-69fq-xp46-6x23).
set -euo pipefail

TRIVY_VERSION="0.76.2"
# SHA-256 of trivy_0.76.2_checksums.txt, as shown next to the asset on
# https://github.com/aquasecurity/trivy/releases/tag/v0.76.2
CHECKSUMS_SHA256="802e4ac1418ed967cd3c4b901f4f71ca00b7363ede67778665a22d9f13f58c83"

mkdir -p ~/.local/bin
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"

base="https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}"
archive="trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"
curl -fsSLO "${base}/trivy_${TRIVY_VERSION}_checksums.txt"
curl -fsSLO "${base}/${archive}"

echo "${CHECKSUMS_SHA256}  trivy_${TRIVY_VERSION}_checksums.txt" | sha256sum --check
grep " ${archive}\$" "trivy_${TRIVY_VERSION}_checksums.txt" | sha256sum --check
tar -xzf "$archive" trivy
install -m 0755 trivy ~/.local/bin/trivy
~/.local/bin/trivy --version
