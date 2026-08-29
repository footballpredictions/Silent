#!/usr/bin/env bash
# Linux AppImage — тот же клиент, что Windows. Запускать из pc/ на Linux.
set -euo pipefail
cd "$(dirname "$0")"

echo '=== Silent VPN Linux: wdtt + wireguard-go + AppImage ==='
printf '%s\n' 'module.exports = { DEBUG_BUILD: false };' > src/main/buildFlags.js
unset DEBUG_BUILD || true
export BOOTSTRAP_VK_HASH="${BOOTSTRAP_VK_HASH:-6EJ_t4eeAb-wbJynEOE-gpHCuaZIYqCRzDB1HZamyxY}"

mkdir -p resources/linux

echo '[1/4] wdtt-client (linux/amd64)...'
(
  cd wdtt-go
  export GOOS=linux GOARCH=amd64 CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=https://proxy.golang.org,direct
  go build -ldflags='-s -w -checklinkname=0' -trimpath -o ../resources/linux/wdtt-client .
)
chmod +x resources/linux/wdtt-client

echo '[2/4] wireguard-go...'
export GOOS=linux GOARCH=amd64 CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=https://proxy.golang.org,direct
if go build -ldflags='-s -w' -trimpath -o resources/linux/wireguard-go golang.zx2c4.com/wireguard@v0.0.20230223; then
  chmod +x resources/linux/wireguard-go
else
  echo 'WARN: wireguard-go build failed — kernel WireGuard + wg'
fi
chmod +x resources/linux/silent-wg-helper

echo '[2b/4] integrity hashes...'
node scripts/gen_integrity_hashes.js

echo "[3/4] renderer (bootstrap $BOOTSTRAP_VK_HASH)..."
rm -rf dist/renderer
npm run build:renderer

echo '[4/4] electron-builder linux dir + .deb installer...'
npx electron-builder --linux dir --publish never --config electron-builder.linux.json
python3 scripts/pack_linux_deb.py || python scripts/pack_linux_deb.py

echo '=== LINUX BUILD SUCCESS ==='
ls -la build-linux/"Silent VPN Setup"*.deb build-linux/silent-vpn_*.deb
