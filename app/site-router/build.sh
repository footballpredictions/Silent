#!/usr/bin/env bash
set -euo pipefail
ROUTER_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$SDK_DIR" ]]; then
  echo 'ANDROID_HOME or ANDROID_SDK_ROOT is required' >&2
  exit 1
fi
NDK_DIR="${ANDROID_NDK_HOME:-}"
if [[ -z "$NDK_DIR" ]]; then
  NDK_VERSION="$(ls -1 "$SDK_DIR/ndk" | sort -V | tail -1)"
  NDK_DIR="$SDK_DIR/ndk/$NDK_VERSION"
fi
case "$(uname -s)" in
  Linux) HOST_TAG=linux-x86_64 ;;
  Darwin) HOST_TAG=darwin-x86_64 ;;
  *) echo 'Use build.ps1 on Windows' >&2; exit 1 ;;
esac
COMPILER_DIR="$NDK_DIR/toolchains/llvm/prebuilt/$HOST_TAG/bin"
cd "$ROUTER_DIR"
build_abi() {
  local abi="$1" arch="$2" compiler="$3" arm="$4" arm64="$5" amd64="$6" x86="$7"
  local output="$ROUTER_DIR/../src/main/jniLibs/$abi/libsite-router.so"
  [[ -x "$COMPILER_DIR/$compiler" ]] || { echo "Missing NDK compiler: $compiler" >&2; exit 1; }
  mkdir -p "$(dirname -- "$output")"
  env GOOS=android CGO_ENABLED=1 GOTOOLCHAIN=go1.26.3 GOARCH="$arch" \
    GOARM="$arm" GOARM64="$arm64" GOAMD64="$amd64" GO386="$x86" \
    CC="$COMPILER_DIR/$compiler" go build -trimpath -ldflags '-s -w' -o "$output" .
  echo "Built site-router $abi"
}
# API 24 matches the application's minSdk; Go >=1.26.3 fixes 32-bit Android SIGSYS.
build_abi arm64-v8a arm64 aarch64-linux-android24-clang '' v8.0 '' ''
build_abi armeabi-v7a arm armv7a-linux-androideabi24-clang 7 '' '' ''
build_abi x86 386 i686-linux-android24-clang '' '' '' sse2
build_abi x86_64 amd64 x86_64-linux-android24-clang '' '' v1 ''
