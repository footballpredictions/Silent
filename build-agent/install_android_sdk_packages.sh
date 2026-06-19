#!/usr/bin/env bash
# Доустановка пакетов Android SDK на VPS (можно запускать повторно).
set -euo pipefail

export ANDROID_HOME=/opt/android-sdk
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

if [[ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]]; then
  echo "Run setup_android_sdk.sh first" >&2
  exit 1
fi

for i in $(seq 1 50); do echo y; done | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1 || true

sdkmanager --sdk_root="$ANDROID_HOME" \
  "platform-tools" \
  "platforms;android-35" \
  "platforms;android-34" \
  "build-tools;35.0.0" \
  "build-tools;34.0.0" \
  "ndk;27.2.12479018"

echo "Installed packages:"
sdkmanager --sdk_root="$ANDROID_HOME" --list_installed | grep -E "build-tools|platforms;android|ndk"
