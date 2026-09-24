#!/usr/bin/env bash
# macOS .dmg — запускать только на Mac (Intel или Apple Silicon — любой собирает оба).
#
#   ./build-mac.sh                  → два DMG: Intel (x64) + Apple Silicon (arm64)
#   MAC_ARCH=amd64 ./build-mac.sh   → только Intel
#   MAC_ARCH=arm64 ./build-mac.sh   → только Apple Silicon
#
# Отдельные DMG, не universal: SHA wdtt-client зашит в app.asar (integrity),
# а universal-упаковка thin-ит fat-бинарь → хеш не совпадает → VPN блокируется.
# DMG — окно «перетащи в Applications» (electron-builder dmg.contents).
set -euo pipefail
cd "$(dirname "$0")"

HOST_ARCH="$(uname -m)"
MODE="${MAC_ARCH:-both}"

case "$MODE" in
  both|universal) GO_ARCHS=(amd64 arm64) ;;
  arm64)          GO_ARCHS=(arm64) ;;
  amd64|x64)      GO_ARCHS=(amd64) ;;
  *) echo "ERROR: MAC_ARCH=both|arm64|amd64"; exit 1 ;;
esac

echo "=== Silent VPN Mac (host=$HOST_ARCH archs=${GO_ARCHS[*]}) ==="
printf '%s\n' 'module.exports = { DEBUG_BUILD: false };' > src/main/buildFlags.js
unset DEBUG_BUILD || true
export BOOTSTRAP_VK_HASH="${BOOTSTRAP_VK_HASH:-T5oeMQkn6iF1XfUfhxGQ0h6j4lHEoJ5wTGEyi1Q_2cc}"
export CGO_ENABLED=0 GOPROXY=https://proxy.golang.org,direct
export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"

mkdir -p resources/mac

build_wireguard_go() {
  local arch="$1" out_wg="$2"
  local ver="${WG_GO_VERSION:-0.0.20230223}"
  local tmp
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/silent-wg-$arch.XXXXXX")"
  (
    cd "$tmp"
    export GOOS=darwin GOARCH="$arch" CGO_ENABLED=0 GOPROXY=https://proxy.golang.org,direct GOTOOLCHAIN=auto
    go mod init tmpwg >/dev/null
    go get "golang.zx2c4.com/wireguard@${ver}"
    go get golang.org/x/sys@v0.30.0 golang.org/x/net@v0.35.0
    go build -ldflags='-s -w -checklinkname=0' -trimpath -o "$out_wg" golang.zx2c4.com/wireguard
  )
  local rc=$?
  rm -rf "$tmp"
  return $rc
}

echo "[1/3] helper..."
if [[ ! -f resources/mac/silent-wg-helper ]]; then
  echo "ERROR: resources/mac/silent-wg-helper missing"
  exit 1
fi
# LF only (не python heredoc — ломал set -e)
perl -pi -e 's/\r\n/\n/g; s/\r/\n/g' resources/mac/silent-wg-helper 2>/dev/null \
  || sed -i '' $'s/\r$//' resources/mac/silent-wg-helper
chmod +x resources/mac/silent-wg-helper
/usr/bin/python3 -m py_compile resources/mac/silent-wg-helper
echo "  helper ok"

deps_native_ok() {
  node -e "require('rollup/dist/native.js')" >/dev/null 2>&1 || return 1
  if [[ -d node_modules/esbuild ]]; then
    node -e "require('esbuild').transformSync('1')" >/dev/null 2>&1 || return 1
  fi
  return 0
}

echo "[deps] node_modules под darwin-$HOST_ARCH..."
if [[ ! -d node_modules ]] || ! deps_native_ok; then
  # node_modules с Windows/другой арх. → нет @rollup/rollup-darwin-*, esbuild-darwin-*
  echo "  переустановка зависимостей (npm install)..."
  rm -rf node_modules
  npm install --no-audit --no-fund
  if ! deps_native_ok; then
    # npm bug: lock с Windows без optional darwin-пакетов
    case "$HOST_ARCH" in
      arm64) RARCH=arm64 ;;
      *)     RARCH=x64 ;;
    esac
    npm install --no-save --no-audit --no-fund "@rollup/rollup-darwin-$RARCH"
  fi
  deps_native_ok || { echo "ERROR: rollup/esbuild не грузятся — удалите node_modules и package-lock.json, затем npm install"; exit 1; }
fi
echo "  deps ok"

echo "[2/3] renderer..."
rm -rf dist/renderer
npm run build:renderer
echo "  renderer ok"

rm -rf build-mac
VER="$(node -p "require('./package.json').version")"
BUILT=()

for arch in "${GO_ARCHS[@]}"; do
  if [[ "$arch" == "amd64" ]]; then
    EB_ARCH="--x64"; SLICE="x86_64"; LABEL="x64"; LABEL_RU="Intel"
  else
    EB_ARCH="--arm64"; SLICE="arm64"; LABEL="arm64"; LABEL_RU="Apple Silicon (M1/M2/M3)"
  fi
  echo ""
  echo "[3/3] === ${LABEL_RU}: darwin/${arch} ==="

  echo "  go build wdtt-client..."
  (
    cd wdtt-go
    export GOOS=darwin GOARCH="$arch"
    go build -ldflags='-s -w -checklinkname=0' -trimpath -o ../resources/mac/wdtt-client .
  )
  echo "  go build wireguard-go..."
  build_wireguard_go "$arch" "$PWD/resources/mac/wireguard-go" \
    || { echo "ERROR: wireguard-go $arch failed"; exit 1; }
  chmod +x resources/mac/wdtt-client resources/mac/wireguard-go
  lipo -info resources/mac/wdtt-client
  lipo -info resources/mac/wireguard-go
  if ! grep -a -q 'protect=darwin' resources/mac/wdtt-client; then
    echo "ERROR: wdtt-client без IP_BOUND_IF (protect=darwin) — full tunnel будет мёртв" >&2
    exit 1
  fi

  # Хеш именно этого thin-бинаря → в asar этой сборки.
  node scripts/gen_integrity_hashes.js

  npx electron-builder --mac dmg "$EB_ARCH" --publish never --config electron-builder.mac.json

  DMG_PATH="build-mac/Silent VPN Setup ${VER}-${LABEL}.dmg"
  APP_PATH="$(find build-mac -maxdepth 2 -name 'Silent VPN.app' -type d -newer resources/mac/wdtt-client 2>/dev/null | head -1 || true)"
  [[ -z "$APP_PATH" ]] && APP_PATH="$(find build-mac -maxdepth 2 -name 'Silent VPN.app' -type d 2>/dev/null | tail -1 || true)"

  # Проверка: в .app нужный arch и тот же wdtt, чей хеш в asar
  if [[ -n "$APP_PATH" ]]; then
    RES="$APP_PATH/Contents/Resources"
    INFO="$(lipo -info "$RES/wdtt-client" 2>&1 || true)"
    echo "  app wdtt: $INFO"
    if ! echo "$INFO" | grep -q "$SLICE"; then
      echo "ERROR: в $APP_PATH wdtt-client не $SLICE" >&2
      exit 1
    fi
    if ! cmp -s "$RES/wdtt-client" resources/mac/wdtt-client; then
      echo "ERROR: wdtt-client в .app ≠ собранному (integrity не совпадёт)" >&2
      exit 1
    fi
    EXEC="$APP_PATH/Contents/MacOS/Silent VPN"
    EXEC_INFO="$(lipo -info "$EXEC" 2>&1 || true)"
    echo "  app exec: $EXEC_INFO"
    if ! echo "$EXEC_INFO" | grep -q "$SLICE"; then
      echo "ERROR: Electron в $APP_PATH не $SLICE — на этом Mac программа не откроется" >&2
      exit 1
    fi
    # Подпись уже в mac-after-pack.js, до сборки DMG.
    # Повторный hdiutil -srcfolder стирал окно: программа слева, Applications справа.
    codesign -dv "$APP_PATH" 2>&1 | head -5
  fi

  if [[ ! -f "$DMG_PATH" ]]; then
    echo "ERROR: нет DMG $DMG_PATH" >&2
    exit 1
  fi
  BUILT+=("$DMG_PATH|$LABEL_RU")
done

echo ""
echo "=== MAC BUILD SUCCESS ==="
for item in "${BUILT[@]}"; do
  f="${item%%|*}"
  echo "  ${item##*|}: $f ($(du -h "$f" | cut -f1))"
done
echo "Установка: открыть .dmg → перетащить Silent VPN в Applications."
