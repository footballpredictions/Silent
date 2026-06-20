#!/usr/bin/env bash
set -euo pipefail

BOOTSTRAP_HASH="${1:?bootstrap hash required}"
ROOT="${BUILD_AGENT_ROOT:-/app/build-agent}"
WORKSPACE="${BUILD_AGENT_WORKSPACE:-$ROOT/workspace}"
SECRETS="$ROOT/secrets/android/keystore"
REPO="$WORKSPACE/android"
APP_DIR="$REPO/app"
GRADLE_VERSION="${GRADLE_VERSION:-8.11.1}"
GRADLE_DIR="/opt/gradle-${GRADLE_VERSION}"

export ANDROID_HOME="${ANDROID_HOME:-/opt/android-sdk}"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/default-java}"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

ensure_gradle() {
  if [[ -x "$GRADLE_DIR/bin/gradle" ]]; then
    export PATH="$GRADLE_DIR/bin:$PATH"
    return
  fi
  echo "[build] downloading gradle ${GRADLE_VERSION}"
  # Битая/частичная установка — иначе unzip спрашивает replace? в неинтерактивной сборке → EOF
  rm -rf "$GRADLE_DIR"
  tmp="$(mktemp -d)"
  wget -q "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" -O "$tmp/gradle.zip"
  unzip -q -o "$tmp/gradle.zip" -d /opt
  rm -rf "$tmp"
  if [[ ! -x "$GRADLE_DIR/bin/gradle" ]]; then
    echo "[build] gradle install failed: $GRADLE_DIR/bin/gradle missing" >&2
    exit 1
  fi
  export PATH="$GRADLE_DIR/bin:$PATH"
}

ensure_sdk_packages() {
  local marker="$ANDROID_HOME/.build-agent-packages-ok"
  if [[ -f "$marker" ]]; then
    return
  fi
  if [[ -x "$ROOT/install_android_sdk_packages.sh" ]]; then
    echo "[build] ensuring Android SDK packages"
    bash "$ROOT/install_android_sdk_packages.sh"
    touch "$marker"
  fi
}

bash "$ROOT/sync_repo.sh" android

if [[ ! -d "$APP_DIR" ]]; then
  echo "[build] missing app dir: $APP_DIR" >&2
  exit 1
fi

if [[ -d "$SECRETS" ]]; then
  mkdir -p "$REPO/keystore"
  cp -a "$SECRETS/." "$REPO/keystore/"
fi

ensure_sdk_packages
ensure_gradle
bash "$ROOT/build_android_go.sh" "$APP_DIR"
cd "$APP_DIR"

echo "[build] android release bootstrap=$BOOTSTRAP_HASH"
gradle assembleRelease -PbootstrapVkHash="$BOOTSTRAP_HASH" --no-daemon -q

APK="$(find "$APP_DIR/build/outputs/apk/release" -maxdepth 1 -name '*.apk' -type f | head -1)"
if [[ -z "$APK" || ! -f "$APK" ]]; then
  echo "[build] APK not found under $APP_DIR/build/outputs/apk/release" >&2
  exit 1
fi
echo "$APK"
