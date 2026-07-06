#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_HASH="${1:?bootstrap hash required}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
WORKSPACE="${BUILD_AGENT_WORKSPACE:-$ROOT/workspace}"
REPO="$WORKSPACE/pc"
OUT_DIR="build-release-agent"
WINE_IMAGE="${PC_BUILDER_IMAGE:-electronuserland/builder:wine}"
GO_IMAGE="${PC_GO_BUILDER_IMAGE:-golang:1.24-bookworm}"
# Без wdtt-client.exe установщик ~79 MB; с wdtt ~83 MB
MIN_INSTALLER_BYTES="${PC_MIN_INSTALLER_BYTES:-81000000}"
MIN_WDTT_BYTES="${PC_MIN_WDTT_BYTES:-500000}"

# shellcheck source=ensure_go.sh
source "$ROOT/ensure_go.sh"

pre_clean_workspace() {
  echo "[build] pre-clean pc workspace"
  rm -rf \
    "$REPO/node_modules" \
    "$REPO/dist" \
    "$REPO/build-release-agent" \
    "$REPO/build-output"
  rm -rf "$REPO"/build-release-v* "$REPO"/build-output-v* "$REPO"/build-fresh
}

bash "$ROOT/sync_repo.sh" pc

restore_wdtt_from_git() {
  local f="$REPO/resources/wdtt-client.exe"
  if [[ -f "$f" ]]; then
    return 0
  fi
  if git -C "$REPO" ls-files --error-unmatch resources/wdtt-client.exe >/dev/null 2>&1; then
    echo "[build] restore wdtt-client.exe from git index"
    git -C "$REPO" checkout HEAD -- resources/wdtt-client.exe
  fi
}

if [[ ! -f "$REPO/package.json" ]]; then
  echo "[build] missing package.json in $REPO" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "[build] node/npm not found in API container" >&2
  exit 1
fi

pre_clean_workspace
restore_wdtt_from_git

# docker.sock монтирует путь ХОСТА (BUILD_AGENT_HOST_ROOT), не /app/... внутри API-контейнера
docker_repo_path() {
  local host_root="${BUILD_AGENT_HOST_ROOT:-}"
  if [[ -n "$host_root" ]]; then
    echo "${host_root}/workspace/pc"
  else
    echo "$REPO"
  fi
}

verify_wdtt_pe() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[build] wdtt-client.exe missing: $path" >&2
    return 1
  fi
  local sz magic
  sz="$(wc -c < "$path" | tr -d ' ')"
  if [[ "$sz" -lt "$MIN_WDTT_BYTES" ]]; then
    echo "[build] wdtt-client.exe too small ($sz bytes): $path" >&2
    return 1
  fi
  magic="$(head -c 2 "$path" | od -An -tx1 | tr -d ' \n')"
  if [[ "${magic,,}" != "4d5a" ]]; then
    echo "[build] wdtt-client.exe is not Windows PE (magic=$magic): $path" >&2
    return 1
  fi
  echo "[build] wdtt-client.exe OK ($sz bytes, PE) at $path"
}

build_wdtt_client_host() {
  echo "[build] wdtt-client.exe (API container, linux -> windows)"
  mkdir -p "$REPO/resources"
  cd "$REPO/wdtt-go"
  unset GOOS GOARCH GOARM CGO_ENABLED
  go mod download
  GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
    go build -ldflags="-s -w -checklinkname=0" -trimpath -o ../resources/wdtt-client.exe .
  verify_wdtt_pe "$REPO/resources/wdtt-client.exe"
}

build_wdtt_client_docker() {
  local docker_repo
  docker_repo="$(docker_repo_path)"
  echo "[build] wdtt-client.exe via $GO_IMAGE (mount $docker_repo)"
  mkdir -p "$REPO/resources"
  docker pull "$GO_IMAGE"
  docker run --rm \
    --entrypoint /usr/bin/bash \
    -v "${docker_repo}:/project" \
    -w /project/wdtt-go \
    -e PATH=/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    -e GOTOOLCHAIN=auto \
    -e GOOS=windows \
    -e GOARCH=amd64 \
    -e CGO_ENABLED=0 \
    "$GO_IMAGE" \
    -c 'set -euo pipefail
      command -v go >/dev/null || { echo "go not in PATH: $PATH" >&2; exit 127; }
      go version
      go mod download
      go build -ldflags="-s -w -checklinkname=0" -trimpath -o ../resources/wdtt-client.exe .
      test -f ../resources/wdtt-client.exe
      sz=$(wc -c < ../resources/wdtt-client.exe | tr -d " ")
      if [[ "$sz" -lt '"$MIN_WDTT_BYTES"' ]]; then
        echo "wdtt-client.exe too small: $sz bytes" >&2
        exit 1
      fi
      magic=$(head -c 2 ../resources/wdtt-client.exe | od -An -tx1 | tr -d " \n")
      if [[ "${magic,,}" != "4d5a" ]]; then
        echo "wdtt-client.exe is not PE (magic=$magic)" >&2
        exit 1
      fi
      echo "wdtt-client.exe OK ($sz bytes, PE)"'
  verify_wdtt_pe "$REPO/resources/wdtt-client.exe"
}

build_wdtt_client() {
  local existing="$REPO/resources/wdtt-client.exe"
  local force_rebuild="${PC_FORCE_REBUILD_WDTT:-0}"

  # Если валидный Windows PE уже есть в репо — используем его.
  # Это исключает падения на шаге go/docker в build-agent и гарантирует, что файл попадёт в installer.
  if [[ "$force_rebuild" != "1" && -f "$existing" ]]; then
    if verify_wdtt_pe "$existing"; then
      echo "[build] reuse wdtt-client.exe from repo"
      return 0
    fi
    echo "[build] existing wdtt-client.exe invalid, rebuilding..." >&2
  fi

  if command -v go >/dev/null 2>&1; then
    build_wdtt_client_host
  elif [[ -S /var/run/docker.sock ]] && command -v docker >/dev/null 2>&1; then
    build_wdtt_client_docker
  else
    echo "[build] go not found and docker unavailable" >&2
    exit 1
  fi
}

build_renderer() {
  echo "[build] npm ci + vite (linux, node $(node -v))"
  cd "$REPO"
  export BOOTSTRAP_VK_HASH="$BOOTSTRAP_HASH"
  rm -rf node_modules dist/renderer
  npm ci --no-audit --no-fund --legacy-peer-deps
  npm run build:renderer
  css=""
  for f in dist/renderer/assets/*.css; do
    if [[ -f "$f" ]]; then
      css="$f"
      break
    fi
  done
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
  local docker_repo
  docker_repo="$(docker_repo_path)"

  if [[ ! -f "$REPO/package.json" ]]; then
    echo "[build] package.json missing in container: $REPO" >&2
    exit 1
  fi

  verify_wdtt_pe "$REPO/resources/wdtt-client.exe"

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
      test -f /project/resources/wdtt-client.exe
      magic=\$(head -c 2 /project/resources/wdtt-client.exe | od -An -tx1 | tr -d ' \n')
      if [[ \"\${magic,,}\" != \"4d5a\" ]]; then
        echo \"wdtt-client.exe missing or not PE in wine mount (magic=\$magic)\" >&2
        exit 1
      fi
      rm -rf '$OUT_DIR'
      npx --yes electron-builder --win nsis --publish never --config.directories.output='$OUT_DIR'
      test -f '/project/$OUT_DIR/win-unpacked/resources/wdtt-client.exe'
      echo \"[build] win-unpacked contains wdtt-client.exe\"
    "

  local exe exe_size
  exe="$(find "$REPO/$OUT_DIR" -maxdepth 1 -name '*.exe' -type f | head -1)"
  if [[ -z "$exe" || ! -f "$exe" ]]; then
    echo "[build] installer exe not found in $REPO/$OUT_DIR" >&2
    exit 1
  fi
  exe_size="$(wc -c < "$exe" | tr -d ' ')"
  if [[ "$exe_size" -lt "$MIN_INSTALLER_BYTES" ]]; then
    echo "[build] installer too small ($exe_size bytes < $MIN_INSTALLER_BYTES) — likely missing wdtt-client.exe" >&2
    exit 1
  fi
  echo "[build] installer OK: $exe ($exe_size bytes)"
  echo "$exe"
}

echo "[build] pc release bootstrap=$BOOTSTRAP_HASH"
build_renderer
build_wdtt_client

if [[ -S /var/run/docker.sock ]] && command -v docker >/dev/null 2>&1; then
  build_installer_in_docker
else
  echo "[build] PC NSIS requires Docker with wine image" >&2
  exit 1
fi
