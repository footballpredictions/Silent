#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_HASH="${1:?bootstrap hash required}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
WORKSPACE="${BUILD_AGENT_WORKSPACE:-$ROOT/workspace}"
REPO="$WORKSPACE/pc"
OUT_DIR="build-release-agent"
WINE_IMAGE="${PC_BUILDER_IMAGE:-electronuserland/builder:wine}"

# shellcheck source=ensure_go.sh
source "$ROOT/ensure_go.sh"

bash "$ROOT/sync_repo.sh" pc

if [[ ! -f "$REPO/package.json" ]]; then
  echo "[build] missing package.json in $REPO" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "[build] node/npm not found in API container" >&2
  exit 1
fi

build_wdtt_client() {
  echo "[build] wdtt-client.exe (linux -> windows)"
  cd "$REPO/wdtt-go"
  go mod download
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
    go build -ldflags="-s -w" -trimpath -o ../resources/wdtt-client.exe .
  test -f ../resources/wdtt-client.exe
  echo "[build] wdtt-client.exe OK"
}

build_renderer() {
  echo "[build] npm ci + vite (linux, node $(node -v))"
  cd "$REPO"
  export BOOTSTRAP_VK_HASH="$BOOTSTRAP_HASH"
  rm -rf node_modules dist/renderer
  npm ci --no-audit --no-fund --legacy-peer-deps
  npm run build:renderer
  css="$(find dist/renderer/assets -name '*.css' -type f | head -1)"
  if [[ -z "$css" || ! -s "$css" ]]; then
    echo "[build] renderer CSS missing" >&2
    exit 1
  fi
  css_size="$(wc -c < "$css")"
  if [[ "$css_size" -lt 8000 ]]; then
    echo "[build] renderer CSS too small ($css_size bytes)" >&2
    exit 1
  fi
  echo "[build] renderer OK ($css_size bytes CSS)"
}

build_installer_in_docker() {
  # docker.sock на хосте: volume — путь ХОСТА, не /app/... внутри API-контейнера
  local host_root="${BUILD_AGENT_HOST_ROOT:-}"
  local docker_repo="$REPO"
  if [[ -n "$host_root" ]]; then
    docker_repo="${host_root}/workspace/pc"
  fi

  if [[ ! -f "$REPO/package.json" ]]; then
    echo "[build] package.json missing in container: $REPO" >&2
    exit 1
  fi

  echo "[build] electron-builder NSIS via $WINE_IMAGE"
  echo "[build] docker mount: ${docker_repo} -> /project"
  docker pull "$WINE_IMAGE"

  docker run --rm \
    -v "${docker_repo}:/project" \
    -w /project \
    -e BOOTSTRAP_VK_HASH="$BOOTSTRAP_HASH" \
    -e ELECTRON_BUILDER_ALLOW_UNRESOLVED_DEPENDENCIES=true \
    "$WINE_IMAGE" \
    /bin/bash -lc "
      set -euo pipefail
      test -f /project/package.json
      rm -rf '$OUT_DIR'
      npx --yes electron-builder --win nsis --publish never --config.directories.output='$OUT_DIR'
    "

  local exe
  exe="$(find "$REPO/$OUT_DIR" -maxdepth 1 -name '*.exe' -type f | head -1)"
  if [[ -z "$exe" || ! -f "$exe" ]]; then
    echo "[build] installer exe not found in $REPO/$OUT_DIR" >&2
    exit 1
  fi
  echo "[build] installer OK: $exe"
  echo "$exe"
}

echo "[build] pc release bootstrap=$BOOTSTRAP_HASH"
build_wdtt_client
build_renderer

if [[ -S /var/run/docker.sock ]] && command -v docker >/dev/null 2>&1; then
  build_installer_in_docker
else
  echo "[build] PC NSIS requires Docker with wine image" >&2
  exit 1
fi
