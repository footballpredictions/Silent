#!/usr/bin/env bash
# Cross-compile wdtt libclient.so for Android (Linux host / Docker API container).
set -euo pipefail

APP_DIR="${1:?app dir required}"
GO_CLIENT_DIR="$APP_DIR/wdtt-go"
JNI_DIR="$APP_DIR/src/main/jniLibs"

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/default-java}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
# shellcheck source=ensure_go.sh
source "$ROOT/ensure_go.sh"

NDK_ROOT="$ANDROID_HOME/ndk"
if [[ ! -d "$NDK_ROOT" ]]; then
  echo "[go] NDK not found under $NDK_ROOT — install via install_android_sdk_packages.sh" >&2
  exit 1
fi

NDK_VER="$(ls -1 "$NDK_ROOT" | sort -V | tail -1)"
TOOLCHAIN="$NDK_ROOT/$NDK_VER/toolchains/llvm/prebuilt/linux-x86_64/bin"
CC_ARM64="$TOOLCHAIN/aarch64-linux-android29-clang"
CC_ARM32="$TOOLCHAIN/armv7a-linux-androideabi29-clang"

if [[ ! -x "$CC_ARM64" || ! -x "$CC_ARM32" ]]; then
  echo "[go] NDK clang not found in $TOOLCHAIN" >&2
  exit 1
fi

echo "[go] using NDK $NDK_VER"
mkdir -p "$JNI_DIR/arm64-v8a" "$JNI_DIR/armeabi-v7a"
cd "$GO_CLIENT_DIR"
go mod download

export GOOS=android CGO_ENABLED=1
export GOARCH=arm64 GOARM=
export CC="$CC_ARM64"
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "$JNI_DIR/arm64-v8a/libclient.so" .

export GOARCH=arm GOARM=7
export CC="$CC_ARM32"
go build -ldflags="-s -w -checklinkname=0" -trimpath -o "$JNI_DIR/armeabi-v7a/libclient.so" .

echo "[go] libclient.so OK"
