#!/usr/bin/env bash
# Принудительно поставить silent-wg-helper из .app в PrivilegedHelperTools
# и перезапустить LaunchDaemon. Нужен пароль администратора.
#
#   chmod +x mac-force-helper.sh && ./mac-force-helper.sh
#
set -euo pipefail

APP_HELPER="/Applications/Silent VPN.app/Contents/Resources/silent-wg-helper"
SYS_HELPER="/Library/PrivilegedHelperTools/silent-vpn-wg-helper"
PLIST="/Library/LaunchDaemons/ru.silent.vpn.helper.plist"
LABEL="ru.silent.vpn.helper"
SOCK="/var/run/silent-vpn/helper.sock"

echo "=== Silent VPN: force helper upgrade ==="

# Если рядом лежит исправленный helper (с флешки/сборки) — берём его, не битый из .app
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_RES="/Applications/Silent VPN.app/Contents/Resources"
for cand in \
  "$SCRIPT_DIR/resources/mac/silent-wg-helper" \
  "$SCRIPT_DIR/silent-wg-helper" \
  "$APP_HELPER"
do
  if [[ -f "$cand" ]]; then
    SRC_HELPER="$cand"
    break
  fi
done

# wdtt-client не копируем: его SHA зашит в app.asar (integrity) — только ./mac-test-cycle.sh.
if [[ -f "$APP_RES/wdtt-client" ]] && ! grep -a -q 'protect=darwin' "$APP_RES/wdtt-client" 2>/dev/null; then
  echo "WARN: в .app старый wdtt-client без IP_BOUND_IF — нужен ./mac-test-cycle.sh (полная сборка)" >&2
fi
if [[ -z "${SRC_HELPER:-}" || ! -f "$SRC_HELPER" ]]; then
  echo "ERROR: нет silent-wg-helper — положите рядом или поставьте .app" >&2
  exit 1
fi

echo "Источник: $SRC_HELPER"

WORK="$(mktemp /tmp/silent-wg-helper.XXXXXX)"
PRIV=""
trap 'rm -f "$WORK" ${PRIV:+"$PRIV"} 2>/dev/null || true' EXIT

cp "$SRC_HELPER" "$WORK"
perl -pi -e 's/\r\n/\n/g; s/\r/\n/g' "$WORK" 2>/dev/null || true
# Типичный typo из правок под Windows/JS (строка 312)
if grep -q 'stdout ||' "$WORK" 2>/dev/null; then
  echo "Патч: p.stdout || → p.stdout or"
fi
perl -pi -e 's/\(p\.stdout \|\| ""\)/(p.stdout or "")/g; s/\(p\.stderr \|\| ""\)/(p.stderr or "")/g' "$WORK"
chmod +x "$WORK" || true

if ! /usr/bin/python3 -m py_compile "$WORK" 2>/tmp/silent-helper-syntax.err; then
  echo "ERROR: silent-wg-helper — SyntaxError даже после патча:" >&2
  cat /tmp/silent-helper-syntax.err >&2
  exit 1
fi
echo "OK: syntax (py_compile)"

if ! grep -q 'competitors-off' "$WORK" 2>/dev/null; then
  echo "WARN: в helper нет competitors-off — это СТАРЫЙ билд. Нужна полная пересборка." >&2
fi

for n in V2BOX V2box Happ "Happ Plus" HappPlus "Urban VPN Desktop" "Urban VPN" UrbanVPN v2RayTun v2raytun freevpn.pw FreeVPN freevpn; do
  killall -KILL "$n" 2>/dev/null || true
done

PRIV="$(mktemp /tmp/silent-force-helper.XXXXXX.sh)"

cat >"$PRIV" <<EOF
#!/bin/bash
set -e
mkdir -p /Library/PrivilegedHelperTools /var/run/silent-vpn /Library/LaunchDaemons
launchctl bootout system/${LABEL} 2>/dev/null || true
pkill -f silent-vpn-wg-helper 2>/dev/null || true
rm -f ${SOCK}
cp "${WORK}" "${SYS_HELPER}"
chmod 755 "${SYS_HELPER}"
chown root:wheel "${SYS_HELPER}"
# И в .app — чтобы снова не подтянуть битый
if [[ -d "${APP_RES}" ]]; then
  cp "${WORK}" "${APP_HELPER}"
  chmod 755 "${APP_HELPER}"
fi
cat > "${PLIST}" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>ru.silent.vpn.helper</string>
<key>ProgramArguments</key><array>
<string>/usr/bin/python3</string>
<string>/Library/PrivilegedHelperTools/silent-vpn-wg-helper</string>
<string>serve</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardErrorPath</key><string>/var/run/silent-vpn/helper.err</string>
<key>StandardOutPath</key><string>/var/run/silent-vpn/helper.out</string>
</dict></plist>
PLIST
launchctl bootstrap system "${PLIST}" 2>/dev/null || true
launchctl enable system/${LABEL} 2>/dev/null || true
launchctl kickstart -k system/${LABEL} 2>/dev/null || true
sleep 1
if ! /usr/bin/python3 -c "import socket;s=socket.socket(socket.AF_UNIX);s.settimeout(0.3);s.connect('${SOCK}')" 2>/dev/null; then
  /usr/bin/python3 "${SYS_HELPER}" serve >/var/run/silent-vpn/helper.out 2>/var/run/silent-vpn/helper.err &
  sleep 1
fi
/usr/bin/python3 -m py_compile "${SYS_HELPER}"
EOF
chmod 700 "$PRIV"

echo "Запрос пароля (osascript)…"
# Только путь к файлу — без вложенного shell в AppleScript.
osascript -e "do shell script \"/bin/bash $(printf %q "$PRIV")\" with administrator privileges"

echo -n "Жду живой helper (connect)… "
READY=0
for i in $(seq 1 60); do
  if python3 - <<'PY' 2>/dev/null
import socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(0.4)
try:
    s.connect("/var/run/silent-vpn/helper.sock")
    s.close()
    raise SystemExit(0)
except Exception:
    raise SystemExit(1)
PY
  then
    echo "OK (${i})"
    READY=1
    break
  fi
  if (( i % 10 == 0 )); then
    osascript -e "do shell script \"launchctl kickstart -k system/${LABEL}; /usr/bin/python3 ${SYS_HELPER} serve >/var/run/silent-vpn/helper.out 2>/var/run/silent-vpn/helper.err &\" with administrator privileges" 2>/dev/null || true
  fi
  sleep 0.25
done

if [[ "$READY" != "1" ]]; then
  echo "FAIL" >&2
  echo "--- helper.err / launchctl ---" >&2
  osascript -e 'do shell script "tail -80 /var/run/silent-vpn/helper.err 2>/dev/null; echo ---; launchctl print system/ru.silent.vpn.helper 2>&1 | head -40"' with administrator privileges 2>&1 || true
  exit 1
fi

python3 - <<'PY'
import json, socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(8)
s.connect("/var/run/silent-vpn/helper.sock")
s.sendall((json.dumps({"args": ["competitors-off"]}) + "\n").encode())
buf = b""
while b"\n" not in buf:
    chunk = s.recv(4096)
    if not chunk:
        break
    buf += chunk
s.close()
line = buf.decode(errors="replace").strip()
print("competitors-off →", line[:240])
if "unknown command" in line.lower():
    print("FAIL: system helper всё ещё старый", file=sys.stderr)
    sys.exit(1)
print("OK: helper новый")
PY

python3 - <<'PY' 2>/dev/null || true
import json, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(8)
s.connect("/var/run/silent-vpn/helper.sock")
for args in (["down"], ["dns-restore"], ["hosts-restore"], ["ipv6-restore"], ["protect-off"]):
    s.sendall((json.dumps({"args": args}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    print(args[0], buf.decode(errors="replace").strip()[:120])
s.close()
PY

echo "=== done ==="
echo "Дальше: ./mac-test-cycle.sh"
echo "Потом ~/Library/Logs/Silent VPN/SilentVPN-main.log на флешку."
