#!/bin/bash
# Собирает libwdtt.a для iOS из того же клиента, что Android (wdtt-go).
# Запускать на Mac из любой папки: bash ios/scripts/build-libwdtt.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MONO="$(cd "$ROOT/.." && pwd)"
SRC="$MONO/android/app/wdtt-go"
OUT="$ROOT/SilentTunnel/Native"
EXPORT="$ROOT/engine/ios_export.go"

if [[ ! -d "$SRC" ]]; then
  echo "Не найден $SRC"
  echo "Нужна папка Silent-Project, где рядом лежат android/ и ios/."
  exit 1
fi
if ! command -v go >/dev/null 2>&1; then
  echo "Нет Go. Поставьте версию из android/app/wdtt-go/go.mod (сейчас 1.26) с https://go.dev/dl/"
  exit 1
fi
if ! xcrun --sdk iphoneos --show-sdk-path >/dev/null 2>&1; then
  echo "Нет iPhone SDK. Откройте Xcode и дождитесь установки платформы iOS."
  exit 1
fi

go test "$ROOT/engine/wg_config.go" "$ROOT/engine/wg_config_test.go"
go test "$ROOT/engine/relay_start.go" "$ROOT/engine/relay_start_test.go"
go test "$ROOT/engine/relay_journal.go" "$ROOT/engine/relay_journal_test.go"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
xcrun swiftc -parse-as-library "$ROOT/Silent/Services/PublicApiFailover.swift" \
  "$ROOT/Silent/Services/BootstrapHTTPResponse.swift" \
  "$ROOT/Silent/Services/BootstrapLaunch.swift" \
  "$ROOT/Silent/Services/PaymentRoute.swift" "$ROOT/Silent/Services/ServerConfigCache.swift" \
  "$ROOT/Silent/Models/Models.swift" \
  "$ROOT/Shared/AppIdentity.swift" "$ROOT/Shared/RussianServices.swift" \
  "$ROOT/scripts/test-session-api-policy.swift" -o "$TMP/silent-session-policy"
"$TMP/silent-session-policy"
rm "$TMP/silent-session-policy"
cp -R "$SRC/." "$TMP/"
cp "$EXPORT" "$ROOT/engine/wg_config.go" "$ROOT/engine/relay_start.go" "$ROOT/engine/relay_journal.go" "$TMP/"
cp "$ROOT/engine/platform_limits_ios.go" "$TMP/"
sed '1s/!android || !arm/(!android || !arm) \&\& !ios/' "$SRC/platform_limits_default.go" > "$TMP/platform_limits_default.go"
# The shared client targets large Android traffic bursts. Keep the per-worker
# packet queue bounded independently in the smaller iOS extension process.
sed -E 's/(workerSendBuf[[:space:]]*=[[:space:]]*)2048/\1256/' "$SRC/session.go" > "$TMP/session.go"
grep -Eq 'workerSendBuf[[:space:]]*=[[:space:]]*256' "$TMP/session.go"
# Shared domain policy and userspace DIRECT transport, same as Android.
cp "$MONO/android/app/site-router/russian.go" "$TMP/russian.go"
cp "$MONO/android/app/site-router/packet.go" "$TMP/russian_packet.go"
sed '1s/linux || android/ios/' "$MONO/android/app/site-router/direct.go" > "$TMP/russian_direct.go"
cd "$TMP"

echo "Качаю WireGuard…"
env -u GOOS -u GOARCH go get golang.zx2c4.com/wireguard@v0.0.0-20261006164505-2631ce99a06f gvisor.dev/gvisor@v0.0.0-20250503011706-39ed1f5ac29c

SDK="$(xcrun --sdk iphoneos --show-sdk-path)"
export GOOS=ios
export GOARCH=arm64
export CGO_ENABLED=1
export CC="$(xcrun --sdk iphoneos --find clang)"
export CGO_CFLAGS="-isysroot ${SDK} -arch arm64 -miphoneos-version-min=16.0"
export CGO_LDFLAGS="-isysroot ${SDK} -arch arm64 -miphoneos-version-min=16.0"

mkdir -p "$OUT"
echo "Собираю libwdtt.a …"
# The temporary module also contains the iOS bridge and shared routing sources.
go build -mod=mod -tags ios -ldflags '-s -w -checklinkname=0' -buildmode=c-archive -o "$OUT/libwdtt.a" .

echo "Готово: $OUT/libwdtt.a"
echo "Дальше в папке ios: xcodegen generate && open Silent.xcodeproj"
echo "Перед Archive скрипт Xcode сам подключит эту библиотеку вместо заглушки."
