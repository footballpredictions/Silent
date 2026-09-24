#!/usr/bin/env bash
# Аварийно вернуть интернет на Mac, если тумблер Silent VPN оставил чёрную дыру.
# Запуск: chmod +x mac-restore-net.sh && ./mac-restore-net.sh
set -euo pipefail

echo "=== Silent VPN: restore net ==="
pkill -f 'Silent VPN' 2>/dev/null || true
pkill -f 'wdtt-client' 2>/dev/null || true
pkill -f 'wireguard-go' 2>/dev/null || true
for n in V2BOX V2box Happ "Happ Plus" HappPlus "Urban VPN Desktop" "Urban VPN" UrbanVPN v2RayTun v2raytun freevpn.pw FreeVPN freevpn; do
  killall -KILL "$n" 2>/dev/null || true
done
sleep 1

HELPER="/Library/PrivilegedHelperTools/silent-vpn-wg-helper"
SOCK="/var/run/silent-vpn/helper.sock"
APP_HELPER="/Applications/Silent VPN.app/Contents/Resources/silent-wg-helper"

run_down() {
  if [[ -S "$SOCK" ]]; then
    python3 - <<'PY' 2>/dev/null || true
import json, socket
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(8)
s.connect("/var/run/silent-vpn/helper.sock")
for args in (
    ["down"],
    ["protect-off"],
    ["dns-restore"],
    ["hosts-restore"],
    ["ipv6-restore"],
):
    s.sendall((json.dumps({"args": args}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    print(args[0], buf.decode(errors="replace").strip()[:200])
s.close()
PY
    return 0
  fi
  if [[ -x "$HELPER" ]]; then
    "$HELPER" down || true
    "$HELPER" protect-off || true
    "$HELPER" dns-restore || true
    "$HELPER" hosts-restore || true
    "$HELPER" ipv6-restore || true
    return 0
  fi
  if [[ -x "$APP_HELPER" ]]; then
    echo "helper daemon нет — пробую через osascript (нужен пароль)…"
    osascript -e "do shell script \"'$APP_HELPER' down; '$APP_HELPER' protect-off; '$APP_HELPER' dns-restore; '$APP_HELPER' hosts-restore; '$APP_HELPER' ipv6-restore\" with administrator privileges" || true
    return 0
  fi
  echo "ERROR: helper не найден" >&2
  return 1
}

run_down
echo "Проверь Safari / ping 1.1.1.1"
echo "Если снова ломается после включения VPN — ./mac-force-helper.sh затем полная ./mac-test-cycle.sh"
echo "=== done ==="
