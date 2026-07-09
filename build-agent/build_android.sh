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
export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$ROOT/.gradle-cache/android}"

pre_clean_workspace() {
  echo "[build] pre-clean android workspace"
  rm -rf \
    "$REPO/app/build" \
    "$REPO/app/.gradle" \
    "$REPO/.gradle" \
    "$REPO/build" \
    "$GRADLE_USER_HOME"
  mkdir -p "$GRADLE_USER_HOME"
}

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

if [[ ! -d "$SECRETS" ]]; then
  echo "[build] missing keystore secrets: $SECRETS" >&2
  echo "[build] deploy: python scripts/pack_build_secrets.py && python scripts/deploy_build_agent.py" >&2
  exit 1
fi
if [[ ! -f "$SECRETS/keystore.properties" ]]; then
  echo "[build] missing $SECRETS/keystore.properties" >&2
  exit 1
fi
mkdir -p "$REPO/keystore"
cp -a "$SECRETS/." "$REPO/keystore/"
# После git clean/reset keystore мог пропасть — проверяем, что Gradle увидит signingConfig
if [[ ! -f "$REPO/keystore/keystore.properties" ]]; then
  echo "[build] keystore.properties not copied into workspace" >&2
  exit 1
fi

pre_clean_workspace
ensure_sdk_packages
ensure_gradle
bash "$ROOT/build_android_go.sh" "$APP_DIR"

for abi in arm64-v8a armeabi-v7a x86_64 x86; do
  so="$APP_DIR/src/main/jniLibs/$abi/libclient.so"
  if [[ ! -s "$so" ]]; then
    echo "[build] libclient.so missing for $abi — abort release" >&2
    exit 1
  fi
done

cd "$APP_DIR"

echo "[build] android release bootstrap=$BOOTSTRAP_HASH"
gradle assembleRelease -PbootstrapVkHash="$BOOTSTRAP_HASH" --no-daemon -q --no-build-cache

OUT_DIR="$APP_DIR/build/outputs/apk/release"
# AGP кладёт и *-unsigned.apk, и подписанный. find|head без сортировки часто
# берёт unsigned первым (ASCII: '-' < '.' → …-unsigned раньше …release.apk).
mapfile -t APKS < <(
  find "$OUT_DIR" -maxdepth 1 -type f -name '*.apk' ! -name '*unsigned*' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr \
    | awk '{ $1=""; sub(/^ /,""); print }'
)
APK="${APKS[0]:-}"
if [[ -z "$APK" || ! -f "$APK" ]]; then
  echo "[build] signed APK not found under $OUT_DIR (unsigned-only is not publishable)" >&2
  find "$OUT_DIR" -maxdepth 1 -name '*.apk' -type f -printf '  %f\n' 2>/dev/null || true
  exit 1
fi

APKSIGNER="$(ls -1 "$ANDROID_HOME"/build-tools/*/apksigner 2>/dev/null | tail -1 || true)"
if [[ -z "$APKSIGNER" || ! -x "$APKSIGNER" ]]; then
  echo "[build] apksigner not found under $ANDROID_HOME/build-tools" >&2
  exit 1
fi
if ! "$APKSIGNER" verify --min-sdk-version 26 "$APK" >/dev/null 2>&1; then
  echo "[build] APK failed signature verify: $APK" >&2
  "$APKSIGNER" verify --verbose "$APK" 2>&1 | tail -40 >&2 || true
  exit 1
fi
echo "[build] signed OK: $(basename "$APK")"
echo "$APK"
