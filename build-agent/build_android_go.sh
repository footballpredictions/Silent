#!/usr/bin/env bash
# Cross-compile wdtt libclient.so for Android (Linux host / Docker API container).
# MUST stay in sync with android/app/build_android_go.bat (API 24 + Go ≥1.26.3).
set -euo pipefail

APP_DIR="${1:?app dir required}"
GO_CLIENT_DIR="$APP_DIR/wdtt-go"
JNI_DIR="$APP_DIR/src/main/jniLibs"

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/default-java}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
# shellcheck source=ensure_go.sh
source "$ROOT/ensure_go.sh"

# Жёстко (не ${VAR:-default}): ensure_go мог уже выставить auto.
# Go 1.26.0–1.26.2 на 32-bit Android 8–10 → SIGSYS exit 159 (go#77621).
export GOTOOLCHAIN=go1.26.3

NDK_ROOT="$ANDROID_HOME/ndk"
if [[ ! -d "$NDK_ROOT" ]]; then
  echo "[go] NDK not found under $NDK_ROOT — install via install_android_sdk_packages.sh" >&2
  exit 1
fi

NDK_VER="$(ls -1 "$NDK_ROOT" | sort -V | tail -1)"
TOOLCHAIN="$NDK_ROOT/$NDK_VER/toolchains/llvm/prebuilt/linux-x86_64/bin"
# API 24 = minSdk. API 29+ → android_get_device_api_level → CANNOT LINK на Android 9.
ANDROID_API="${ANDROID_API:-24}"
CC_ARM64="$TOOLCHAIN/aarch64-linux-android${ANDROID_API}-clang"
CC_ARM32="$TOOLCHAIN/armv7a-linux-androideabi${ANDROID_API}-clang"
CC_X86_64="$TOOLCHAIN/x86_64-linux-android${ANDROID_API}-clang"
CC_X86="$TOOLCHAIN/i686-linux-android${ANDROID_API}-clang"

if [[ ! -x "$CC_ARM64" || ! -x "$CC_ARM32" ]]; then
  echo "[go] NDK arm clang not found in $TOOLCHAIN (API $ANDROID_API)" >&2
  exit 1
fi
if [[ ! -x "$CC_X86_64" || ! -x "$CC_X86" ]]; then
  echo "[go] NDK x86 clang not found in $TOOLCHAIN (need x86_64 + i686 for TV/emulator)" >&2
  exit 1
fi

echo "[go] using NDK $NDK_VER (API $ANDROID_API, GOTOOLCHAIN=$GOTOOLCHAIN)"
mkdir -p \
  "$JNI_DIR/arm64-v8a" \
  "$JNI_DIR/armeabi-v7a" \
  "$JNI_DIR/x86_64" \
  "$JNI_DIR/x86"
cd "$GO_CLIENT_DIR"
go mod download
go version

export GOOS=android CGO_ENABLED=1
LDFLAGS="-s -w -checklinkname=0"

build_abi() {
  local label="$1"
  local out="$2"
  shift 2
  echo "[go] $label..."
  env "$@" go build -ldflags="$LDFLAGS" -trimpath -o "$out" .
}

build_abi "arm64-v8a" "$JNI_DIR/arm64-v8a/libclient.so" \
  GOARCH=arm64 GOARM= GOARM64=v8.0 GOAMD64= GO386= CC="$CC_ARM64"

build_abi "armeabi-v7a" "$JNI_DIR/armeabi-v7a/libclient.so" \
  GOARCH=arm GOARM=7 GOARM64= GOAMD64= GO386= CC="$CC_ARM32"

build_abi "x86_64" "$JNI_DIR/x86_64/libclient.so" \
  GOARCH=amd64 GOARM= GOARM64= GOAMD64=v1 GO386= CC="$CC_X86_64"

build_abi "x86" "$JNI_DIR/x86/libclient.so" \
  GOARCH=386 GOARM= GOARM64= GOAMD64= GO386=sse2 CC="$CC_X86"

for abi in arm64-v8a armeabi-v7a x86_64 x86; do
  so="$JNI_DIR/$abi/libclient.so"
  if [[ ! -s "$so" ]]; then
    echo "[go] missing libclient.so for $abi" >&2
    exit 1
  fi
  echo "[go] OK $abi ($(stat -c%s "$so" 2>/dev/null || wc -c <"$so") bytes)"
done

echo "[go] libclient.so OK (4 ABIs, API $ANDROID_API, $GOTOOLCHAIN)"
