#!/usr/bin/env bash
# macOS .dmg — тот же клиент, что Windows/Linux.
# ОБЯЗАТЕЛЬНО запускать на Mac (electron-builder --mac не работает с Windows).
set -euo pipefail
cd "$(dirname "$0")"

ARCH="${MAC_ARCH:-arm64}"
echo "=== Silent VPN Mac (${ARCH}): wdtt + wireguard-go + DMG ==="
printf '%s\n' 'module.exports = { DEBUG_BUILD: false };' > src/main/buildFlags.js
unset DEBUG_BUILD || true
export BOOTSTRAP_VK_HASH="${BOOTSTRAP_VK_HASH:-4uhJXsVypBdlEbvt6k4hPEFi3RooXUqyUwDG4lgPBDY}"

mkdir -p resources/mac

echo "[1/4] wdtt-client (darwin/${ARCH})..."
(
  cd wdtt-go
  export GOOS=darwin GOARCH="$ARCH" CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=https://proxy.golang.org,direct
  go build -ldflags='-s -w -checklinkname=0' -trimpath -o ../resources/mac/wdtt-client .
)
chmod +x resources/mac/wdtt-client

echo "[2/4] wireguard-go (darwin/${ARCH})..."
export GOOS=darwin GOARCH="$ARCH" CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=https://proxy.golang.org,direct
if go build -ldflags='-s -w' -trimpath -o resources/mac/wireguard-go golang.zx2c4.com/wireguard@v0.0.20230223; then
  chmod +x resources/mac/wireguard-go
else
  echo 'ERROR: wireguard-go build failed (required on macOS)'
  exit 1
fi
chmod +x resources/mac/silent-wg-helper
# LF endings for helper
python3 - <<'PY' || python - <<'PY'
from pathlib import Path
p = Path('resources/mac/silent-wg-helper')
p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
PY

echo '[2b/4] integrity hashes...'
node scripts/gen_integrity_hashes.js

echo "[3/4] renderer (bootstrap $BOOTSTRAP_VK_HASH)..."
rm -rf dist/renderer
npm run build:renderer

echo '[4/4] electron-builder mac dmg...'
npx electron-builder --mac dmg --publish never --config electron-builder.mac.json

echo '=== MAC BUILD SUCCESS ==='
ls -la build-mac/"Silent VPN Setup"*.dmg 2>/dev/null || ls -la build-mac/*.dmg
