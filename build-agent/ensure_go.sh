#!/usr/bin/env bash
# Официальный Go (не apt golang 1.18). GOTOOLCHAIN=auto подтягивает версию из go.mod.
set -euo pipefail

GO_INSTALL_DIR="${GO_INSTALL_DIR:-/usr/local/go}"
GO_BOOTSTRAP_VERSION="${GO_BOOTSTRAP_VERSION:-1.24.2}"

if [[ -x "$GO_INSTALL_DIR/bin/go" ]]; then
  export PATH="$GO_INSTALL_DIR/bin:$PATH"
  export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"
  return 0 2>/dev/null || exit 0
fi

echo "[go] installing Go ${GO_BOOTSTRAP_VERSION} -> ${GO_INSTALL_DIR}"
tmp="$(mktemp -d)"
wget -q "https://go.dev/dl/go${GO_BOOTSTRAP_VERSION}.linux-amd64.tar.gz" -O "$tmp/go.tgz"
rm -rf "$GO_INSTALL_DIR"
mkdir -p "$(dirname "$GO_INSTALL_DIR")"
tar -C "$(dirname "$GO_INSTALL_DIR")" -xzf "$tmp/go.tgz"
rm -rf "$tmp"
export PATH="$GO_INSTALL_DIR/bin:$PATH"
export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"
go version
