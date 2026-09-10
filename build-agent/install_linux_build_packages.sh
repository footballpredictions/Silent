#!/usr/bin/env bash
# Пакеты и Docker-образ для OTA-сборки Linux (.deb) на VPS.
# Запускать на хосте Улья (не внутри api-контейнера): bash install_linux_build_packages.sh
set -euo pipefail

LINUX_IMAGE="${LINUX_BUILDER_IMAGE:-electronuserland/builder:20}"
GO_IMAGE="${PC_GO_BUILDER_IMAGE:-golang:1.24-bookworm}"

echo "[linux-build] apt packages (host helpers; основная сборка в Docker)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ca-certificates \
  curl \
  wget \
  git \
  python3 \
  xz-utils \
  unzip \
  libarchive-tools \
  fakeroot \
  dpkg-dev \
  binutils \
  || true

if ! command -v docker >/dev/null 2>&1; then
  echo "[linux-build] docker not found — установите Docker для electron-builder" >&2
  exit 1
fi

echo "[linux-build] pull $LINUX_IMAGE (electron-builder linux)"
docker pull "$LINUX_IMAGE"

echo "[linux-build] pull $GO_IMAGE (wdtt / wireguard-go)"
docker pull "$GO_IMAGE"

mkdir -p /opt/silent-vpn/backend/update/linux \
  /opt/silent-vpn/backend/build-agent/workspace/linux

echo "[linux-build] OK"
docker images --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep -E 'electronuserland/builder|golang' || true
