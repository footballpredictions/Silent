#!/usr/bin/env bash
# Mac: сборка → установка в /Applications → лог (ошибки) на Рабочий стол.
#
# Запуск из pc/:
#   chmod +x mac-test-cycle.sh
#   ./mac-test-cycle.sh
#
# Опции:
#   MAC_ARCH=amd64|arm64|universal   (по умолчанию = arch хоста: Intel→amd64, Apple Silicon→arm64)
#   LOG_SECS=120                     сколько секунд писать лог после старта (Enter — раньше)
#   SKIP_BUILD=1                     только поставить уже собранный .app и снять лог
#
set -euo pipefail
cd "$(dirname "$0")"

HOST="$(uname -m)"
if [[ -z "${MAC_ARCH:-}" ]]; then
  case "$HOST" in
    x86_64) MAC_ARCH=amd64 ;;
    arm64)  MAC_ARCH=arm64 ;;
    *)      MAC_ARCH=universal ;;
  esac
fi
export MAC_ARCH
LOG_SECS="${LOG_SECS:-120}"
DESKTOP="${HOME}/Desktop"
STAMP="$(date +%Y%m%d-%H%M%S)"
FULL_LOG="${DESKTOP}/SilentVPN-full-${STAMP}.log"
ERR_LOG="${DESKTOP}/SilentVPN-errors-${STAMP}.log"
MAIN_LOG="${DESKTOP}/SilentVPN-main.log"
APP_NAME="Silent VPN.app"
APP_DST="/Applications/${APP_NAME}"

echo "=== mac-test-cycle (host=$HOST MAC_ARCH=$MAC_ARCH) ==="
echo "Логи → Рабочий стол:"
echo "  $FULL_LOG"
echo "  $ERR_LOG"
echo "  $MAIN_LOG  (WG/VPN/капча — главный сигнал)"

find_built_app() {
  local cand
  for cand in \
    "build-mac/mac-universal/Silent VPN.app" \
    "build-mac/mac/Silent VPN.app" \
    "build-mac/mac-arm64/Silent VPN.app"
  do
    if [[ -d "$cand" ]]; then
      echo "$cand"
      return 0
    fi
  done
  find build-mac -name 'Silent VPN.app' -type d 2>/dev/null | head -1
}

kill_silent() {
  pkill -f 'Silent VPN' 2>/dev/null || true
  pkill -x 'Silent VPN' 2>/dev/null || true
  pkill -f 'wdtt-client' 2>/dev/null || true
  sleep 1
}

if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  echo ""
  echo "[1/4] Сборка…"
  # LF на случай копирования с Windows
  perl -pi -e 's/\r\n/\n/g; s/\r/\n/g' build-mac.sh 2>/dev/null || sed -i '' $'s/\r$//' build-mac.sh
  chmod +x build-mac.sh
  ./build-mac.sh
else
  echo ""
  echo "[1/4] SKIP_BUILD=1 — сборку пропускаю"
fi

APP_SRC="$(find_built_app || true)"
if [[ -z "${APP_SRC:-}" || ! -d "$APP_SRC" ]]; then
  echo "ERROR: нет собранного Silent VPN.app в build-mac/" >&2
  exit 1
fi
echo "  source: $APP_SRC"

echo ""
echo "[2/4] Установка в $APP_DST …"
kill_silent
rm -rf "$APP_DST"
cp -R "$APP_SRC" "$APP_DST"
# бинарники ещё раз (на случай если копировали старый .app)
if [[ -d resources/mac ]]; then
  RES="$APP_DST/Contents/Resources"
  for b in wdtt-client wireguard-go silent-wg-helper; do
    if [[ -f "resources/mac/$b" ]]; then
      cp -f "resources/mac/$b" "$RES/"
      chmod +x "$RES/$b"
    fi
  done
fi

# Проверка: JS-фиксы внутри asar (копирование .js мимо сборки НЕ работает)
ASAR="$APP_DST/Contents/Resources/app.asar"
if [[ -f "$ASAR" ]]; then
  if ! grep -a -q 'findBundledHelper' "$ASAR" 2>/dev/null; then
    echo "ERROR: в app.asar нет findBundledHelper — сборка без свежего wireguardDarwin.js" >&2
    echo "       Нельзя чинить копированием .js на флешку. Нужен ./build-mac.sh" >&2
    exit 1
  fi
  echo "  asar: findBundledHelper OK"
fi
if [[ -f "$APP_DST/Contents/Resources/silent-wg-helper" ]]; then
  if ! grep -q 'competitors-off' "$APP_DST/Contents/Resources/silent-wg-helper"; then
    echo "ERROR: Resources/silent-wg-helper без competitors-off" >&2
    exit 1
  fi
  echo "  helper resource: competitors-off OK"
fi

# System helper из .app (пароль) — иначе живёт старый PrivilegedHelperTools
if [[ -x ./mac-force-helper.sh ]]; then
  echo ""
  echo "[2b] Force system helper (пароль)…"
  perl -pi -e 's/\r\n/\n/g; s/\r/\n/g' mac-force-helper.sh 2>/dev/null || true
  chmod +x mac-force-helper.sh
  ./mac-force-helper.sh || echo "WARN: force-helper не прошёл — при первом WG снова спросит пароль"
fi

{
  echo "=== Silent VPN mac-test-cycle $STAMP ==="
  echo "host=$(uname -a)"
  echo "MAC_ARCH=$MAC_ARCH"
  echo "APP_SRC=$APP_SRC"
  echo "APP_DST=$APP_DST"
  echo ""
  echo "--- lipo ---"
  lipo -info "$APP_DST/Contents/Resources/wdtt-client" 2>&1 || true
  lipo -info "$APP_DST/Contents/Resources/wireguard-go" 2>&1 || true
  file "$APP_DST/Contents/MacOS/"* 2>&1 || true
  echo ""
  echo "--- app start ---"
} >"$FULL_LOG"

echo ""
echo "[3/4] Запуск + лог ${LOG_SECS}с (или Enter чтобы остановить раньше)…"
echo "      В приложении: дождись UI → нажми подключение канала."
kill_silent

export ELECTRON_ENABLE_LOGGING=1
export SILENT_VPN_FILE_LOG="$MAIN_LOG"
: >"$MAIN_LOG" || true
EXE="$APP_DST/Contents/MacOS/Silent VPN"
if [[ ! -x "$EXE" ]]; then
  # иногда бинарь называется иначе
  EXE="$(find "$APP_DST/Contents/MacOS" -type f -perm +111 2>/dev/null | head -1 || true)"
fi
if [[ -z "${EXE:-}" || ! -x "$EXE" ]]; then
  echo "ERROR: нет исполняемого файла в Contents/MacOS" | tee -a "$FULL_LOG" >&2
  exit 1
fi

# Прямой запуск — весь stdout/stderr в лог (open -a потоки не даёт)
"$EXE" >>"$FULL_LOG" 2>&1 &
APP_PID=$!
echo "  pid=$APP_PID exe=$EXE" | tee -a "$FULL_LOG"

# ждём LOG_SECS или Enter
if [[ -t 0 ]]; then
  echo "  Жду ${LOG_SECS}с… Enter = стоп сейчас"
  read -r -t "$LOG_SECS" _ || true
else
  sleep "$LOG_SECS"
fi

# не убиваем приложение — пользователь может продолжать; только снимаем снимок лога

echo ""
echo "[4/4] Выжимка ошибок → $ERR_LOG"
{
  echo "=== Silent VPN ERRORS $STAMP ==="
  echo "Полный stderr: $FULL_LOG"
  echo "Main (WG/VPN): $MAIN_LOG"
  echo ""
  echo "--- SilentVPN-main.log ---"
  if [[ -f "$MAIN_LOG" ]]; then
    cat "$MAIN_LOG"
  else
    echo "(нет $MAIN_LOG — пересобери с новым main.js)"
  fi
  echo ""
  echo "--- stderr signal (без EGL) ---"
  grep -E \
    'ERROR|Error occurred|ReferenceError|TypeError|UnhandledPromise|is not defined|is not a function|spawn Unknown|Bad CPU|Integrity|WG\]|VPN\]|КАПЧА|WDTT|helper|туннел|Таймаут' \
    "$FULL_LOG" 2>/dev/null \
    | grep -Ev 'eglQueryDeviceAttribEXT|GL Driver message|DevTools|Autofill' \
    || echo "(в stderr только EGL / пусто — смотри SilentVPN-main.log)"
} >"$ERR_LOG"

# Копия в репо — чтобы с USB попало на Windows к агенту
mkdir -p logs
cp -f "$ERR_LOG" "logs/mac-last-errors.log"
cp -f "$FULL_LOG" "logs/mac-last-full.log"
[[ -f "$MAIN_LOG" ]] && cp -f "$MAIN_LOG" "logs/mac-last-main.log" || true
grep -E 'ERROR|Error occurred|ReferenceError|TypeError|UnhandledPromise|is not defined|is not a function|spawn Unknown|Bad CPU|Integrity|WG\]|VPN\]|КАПЧА|WDTT|helper|туннел' \
  "$FULL_LOG" "$MAIN_LOG" 2>/dev/null \
  | grep -Ev 'eglQueryDeviceAttribEXT|GL Driver message|DevTools|Autofill' \
  > "logs/mac-last-signal.log" || true
echo "=== ГОТОВО ==="
echo "Приложение: $APP_DST"
echo "Ошибки:     $ERR_LOG"
echo "Main лог:   $MAIN_LOG   ← пришли ЭТОТ файл"
echo "Полный:     $FULL_LOG"
echo "В репо:     logs/mac-last-*.log"
echo ""
echo "Повторить только лог без сборки:"
echo "  SKIP_BUILD=1 LOG_SECS=180 ./mac-test-cycle.sh"
echo "Во время ожидания: капча / логин / тумблер, потом Enter."
