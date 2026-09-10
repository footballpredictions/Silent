#!/usr/bin/env bash
# Linux .deb OTA: ветка pc → workspace/linux, electron-builder dir + pack_linux_deb.py
set -euo pipefail

BOOTSTRAP_HASH="${1:?bootstrap hash required}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
WORKSPACE="${BUILD_AGENT_WORKSPACE:-$ROOT/workspace}"
REPO="$WORKSPACE/linux"
OUT_DIR="build-linux"
LINUX_IMAGE="${LINUX_BUILDER_IMAGE:-electronuserland/builder:20}"
GO_IMAGE="${PC_GO_BUILDER_IMAGE:-golang:1.24-bookworm}"
MIN_DEB_BYTES="${LINUX_MIN_DEB_BYTES:-50000000}"
MIN_WDTT_BYTES="${PC_MIN_WDTT_BYTES:-500000}"
export GOTOOLCHAIN="${PC_GOTOOLCHAIN:-go1.26.3}"

# shellcheck source=ensure_go.sh
source "$ROOT/ensure_go.sh"
export GOTOOLCHAIN="${PC_GOTOOLCHAIN:-go1.26.3}"

pre_clean_workspace() {
  echo "[build] pre-clean linux workspace"
  rm -rf \
    "$REPO/node_modules" \
    "$REPO/dist" \
    "$REPO/build-linux" \
    "$REPO/build-release-agent" \
    "$REPO/build-output"
  rm -rf "$REPO"/build-release-v* "$REPO"/build-output-v* "$REPO"/build-fresh
}

bash "$ROOT/sync_repo.sh" linux

if [[ ! -f "$REPO/package.json" ]]; then
  echo "[build] missing package.json in $REPO" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "[build] node/npm not found in API container" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "[build] python3 required for pack_linux_deb.py" >&2
  exit 1
fi

pre_clean_workspace

docker_repo_path() {
  local host_root="${BUILD_AGENT_HOST_ROOT:-}"
  if [[ -n "$host_root" ]]; then
    echo "${host_root}/workspace/linux"
  else
    echo "$REPO"
  fi
}

verify_elf() {
  local path="$1"
  local label="${2:-binary}"
  if [[ ! -f "$path" ]]; then
    echo "[build] $label missing: $path" >&2
    return 1
  fi
  local sz magic
  sz="$(wc -c < "$path" | tr -d ' ')"
  if [[ "$sz" -lt "$MIN_WDTT_BYTES" ]]; then
    echo "[build] $label too small ($sz bytes): $path" >&2
    return 1
  fi
  magic="$(head -c 4 "$path" | od -An -tx1 | tr -d ' \n')"
  if [[ "${magic,,}" != "7f454c46" ]]; then
    echo "[build] $label is not ELF (magic=$magic): $path" >&2
    return 1
  fi
  echo "[build] $label OK ($sz bytes, ELF) at $path"
}

build_linux_bins_host() {
  echo "[build] linux bins (API container, GOTOOLCHAIN=$GOTOOLCHAIN)"
  mkdir -p "$REPO/resources/linux"
  cd "$REPO/wdtt-go"
  unset GOOS GOARCH GOARM CGO_ENABLED
  go mod download
  go version
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 \
    go build -ldflags="-s -w -checklinkname=0" -trimpath -o ../resources/linux/wdtt-client .
  verify_elf "$REPO/resources/linux/wdtt-client" "wdtt-client"
  cd "$REPO"
  GOOS=linux GOARCH=amd64 CGO_ENABLED=0 \
    go build -ldflags="-s -w" -trimpath -o resources/linux/wireguard-go \
      golang.zx2c4.com/wireguard@v0.0.20230223 || {
      echo "[build] WARN: wireguard-go build failed — kernel WG fallback"
    }
  if [[ -f "$REPO/resources/linux/wireguard-go" ]]; then
    chmod +x "$REPO/resources/linux/wireguard-go" || true
  fi
  chmod +x "$REPO/resources/linux/silent-wg-helper" || true
}

build_linux_bins_docker() {
  local docker_repo
  docker_repo="$(docker_repo_path)"
  echo "[build] linux bins via $GO_IMAGE (mount $docker_repo)"
  mkdir -p "$REPO/resources/linux"
  docker pull "$GO_IMAGE"
  docker run --rm \
    --entrypoint /usr/bin/bash \
    -v "${docker_repo}:/project" \
    -w /project/wdtt-go \
    -e PATH=/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    -e GOTOOLCHAIN="${GOTOOLCHAIN:-go1.26.3}" \
    -e GOOS=linux \
    -e GOARCH=amd64 \
    -e CGO_ENABLED=0 \
    "$GO_IMAGE" \
    -c 'set -euo pipefail
      command -v go >/dev/null || { echo "go not in PATH: $PATH" >&2; exit 127; }
      go version
      go mod download
      go build -ldflags="-s -w -checklinkname=0" -trimpath -o ../resources/linux/wdtt-client .
      test -f ../resources/linux/wdtt-client
      sz=$(wc -c < ../resources/linux/wdtt-client | tr -d " ")
      if [[ "$sz" -lt '"$MIN_WDTT_BYTES"' ]]; then
        echo "wdtt-client too small: $sz" >&2
        exit 1
      fi
      magic=$(head -c 4 ../resources/linux/wdtt-client | od -An -tx1 | tr -d " \n")
      if [[ "${magic,,}" != "7f454c46" ]]; then
        echo "wdtt-client not ELF (magic=$magic)" >&2
        exit 1
      fi
      cd /project
      go build -ldflags="-s -w" -trimpath -o resources/linux/wireguard-go \
        golang.zx2c4.com/wireguard@v0.0.20230223 || echo "WARN wireguard-go failed"
      chmod +x resources/linux/wdtt-client resources/linux/silent-wg-helper 2>/dev/null || true
      chmod +x resources/linux/wireguard-go 2>/dev/null || true
      echo "linux bins OK"'
  verify_elf "$REPO/resources/linux/wdtt-client" "wdtt-client"
}

build_linux_bins() {
  local force_rebuild="${LINUX_FORCE_REBUILD_WDTT:-1}"
  local existing="$REPO/resources/linux/wdtt-client"
  if [[ "$force_rebuild" != "1" && -f "$existing" ]]; then
    if verify_elf "$existing" "wdtt-client"; then
      echo "[build] reuse linux wdtt-client (set LINUX_FORCE_REBUILD_WDTT=1 to rebuild)"
      return 0
    fi
  fi
  if command -v go >/dev/null 2>&1; then
    build_linux_bins_host
  elif [[ -S /var/run/docker.sock ]] && command -v docker >/dev/null 2>&1; then
    build_linux_bins_docker
  else
    echo "[build] go not found and docker unavailable" >&2
    exit 1
  fi
}

build_renderer() {
  echo "[build] npm ci + vite (linux, node $(node -v))"
  cd "$REPO"
  export BOOTSTRAP_VK_HASH="$BOOTSTRAP_HASH"
  printf '%s\n' 'module.exports = { DEBUG_BUILD: false };' > src/main/buildFlags.js
  rm -rf node_modules dist/renderer
  npm ci --no-audit --no-fund --legacy-peer-deps
  node scripts/gen_integrity_hashes.js
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

build_unpacked_in_docker() {
  local docker_repo
  docker_repo="$(docker_repo_path)"
  verify_elf "$REPO/resources/linux/wdtt-client" "wdtt-client"
  if [[ ! -f "$REPO/resources/linux/silent-wg-helper" ]]; then
    echo "[build] silent-wg-helper missing" >&2
    exit 1
  fi

  echo "[build] electron-builder linux dir via $LINUX_IMAGE"
  echo "[build] docker mount: ${docker_repo} -> /project"
  docker pull "$LINUX_IMAGE"

  docker run --rm \
    -v "${docker_repo}:/project" \
    -w /project \
    -e BOOTSTRAP_VK_HASH="$BOOTSTRAP_HASH" \
    -e ELECTRON_BUILDER_ALLOW_UNRESOLVED_DEPENDENCIES=true \
    "$LINUX_IMAGE" \
    /bin/bash -lc "
      set -euo pipefail
      test -f /project/package.json
      test -f /project/resources/linux/wdtt-client
      magic=\$(head -c 4 /project/resources/linux/wdtt-client | od -An -tx1 | tr -d ' \n')
      if [[ \"\${magic,,}\" != \"7f454c46\" ]]; then
        echo \"wdtt-client not ELF in mount (magic=\$magic)\" >&2
        exit 1
      fi
      rm -rf '$OUT_DIR'
      npx --yes electron-builder --linux dir --x64 --publish never --config electron-builder.linux.json
      test -d '/project/$OUT_DIR/linux-unpacked'
      test -f '/project/$OUT_DIR/linux-unpacked/resources/wdtt-client' \
        || test -f '/project/$OUT_DIR/linux-unpacked/resources/app.asar.unpacked/resources/wdtt-client' \
        || echo '[build] WARN: wdtt path in unpacked may differ'
      echo '[build] linux-unpacked ready'
    "
}

pack_deb() {
  cd "$REPO"
  python3 scripts/pack_linux_deb.py
  local version deb
  version="$(python3 -c "import json; print(json.load(open('package.json'))['version'])")"
  deb="$REPO/$OUT_DIR/Silent VPN Setup ${version}.deb"
  if [[ ! -f "$deb" ]]; then
    deb="$(find "$REPO/$OUT_DIR" -maxdepth 1 -name 'Silent VPN Setup *.deb' -type f | head -1)"
  fi
  if [[ -z "${deb:-}" || ! -f "$deb" ]]; then
    echo "[build] .deb not found in $REPO/$OUT_DIR" >&2
    exit 1
  fi
  local sz
  sz="$(wc -c < "$deb" | tr -d ' ')"
  if [[ "$sz" -lt "$MIN_DEB_BYTES" ]]; then
    echo "[build] .deb too small ($sz < $MIN_DEB_BYTES)" >&2
    exit 1
  fi
  echo "[build] linux deb OK: $deb ($sz bytes)"
  echo "$deb"
}

echo "[build] linux release bootstrap=$BOOTSTRAP_HASH"
build_renderer
build_linux_bins

if [[ -S /var/run/docker.sock ]] && command -v docker >/dev/null 2>&1; then
  build_unpacked_in_docker
else
  echo "[build] Linux electron-builder requires Docker ($LINUX_IMAGE)" >&2
  exit 1
fi

pack_deb
