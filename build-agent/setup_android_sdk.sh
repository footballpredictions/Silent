#!/bin/bash
# Установка Android SDK на VPS (один раз).
set -euo pipefail

export ANDROID_HOME=/opt/android-sdk
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

if [[ -d "$ANDROID_HOME/platform-tools" && -d "$ANDROID_HOME/build-tools/34.0.0" ]]; then
  echo "Android SDK already at $ANDROID_HOME"
  exit 0
fi

apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless wget unzip

mkdir -p "$ANDROID_HOME/cmdline-tools"
cd /tmp
wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O cmdtools.zip
rm -rf "$ANDROID_HOME/cmdline-tools/latest"
unzip -q cmdtools.zip -d "$ANDROID_HOME/cmdline-tools"
mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest"
rm -f cmdtools.zip

yes | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1 || true
for i in $(seq 1 50); do echo y; done | sdkmanager --sdk_root="$ANDROID_HOME" --licenses >/dev/null 2>&1 || true
sdkmanager --sdk_root="$ANDROID_HOME" \
  "platform-tools" \
  "platforms;android-35" \
  "platforms;android-34" \
  "build-tools;35.0.0" \
  "build-tools;34.0.0" \
  "ndk;27.2.12479018"

echo "Android SDK ready at $ANDROID_HOME"
sdkmanager --list_installed | head -20
