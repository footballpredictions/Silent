#!/bin/sh
# Hot-patch panel logout/session isolation + devices rename/delete + mobile nav scroll.
# No VERSION bump, no VPN/wdtt restart.
# Expects files in /tmp/sv-panel-session/ (or pass BASE URL to wget).

set -e
BASE="${1:-}"
TMP="/tmp/sv-panel-session"
BK="/tmp/sv-panel-session-backup-$$"

need_lib="session.sh hive.sh"
need_sbin="silent-vpn-ctl"
need_cgi="silent-api"
need_web="index.html app.js api.js app.css"

mkdir -p "$TMP" "$TMP/web" "$BK" "$BK/web"

if [ -n "$BASE" ]; then
	for f in $need_lib; do wget -qO "$TMP/$f" "$BASE/$f" || { echo "download failed: $f"; exit 1; }; done
	for f in $need_sbin; do wget -qO "$TMP/$f" "$BASE/$f" || { echo "download failed: $f"; exit 1; }; done
	for f in $need_cgi; do wget -qO "$TMP/$f" "$BASE/$f" || { echo "download failed: $f"; exit 1; }; done
	for f in $need_web; do wget -qO "$TMP/web/$f" "$BASE/web/$f" || { echo "download failed: web/$f"; exit 1; }; done
fi

for f in $need_lib $need_sbin $need_cgi; do
	[ -s "$TMP/$f" ] || { echo "missing $TMP/$f"; exit 1; }
done
for f in $need_web; do
	[ -s "$TMP/web/$f" ] || { echo "missing $TMP/web/$f"; exit 1; }
done

for f in $need_lib $need_sbin $need_cgi; do
	tr -d '\r' < "$TMP/$f" > "$TMP/$f.lf"
	mv "$TMP/$f.lf" "$TMP/$f"
done
for f in $need_web; do
	tr -d '\r' < "$TMP/web/$f" > "$TMP/web/$f.lf"
	mv "$TMP/web/$f.lf" "$TMP/web/$f"
done

sh -n "$TMP/session.sh"
sh -n "$TMP/hive.sh"
sh -n "$TMP/silent-vpn-ctl"
sh -n "$TMP/silent-api"
grep -q sv_panel_logout "$TMP/session.sh" || { echo "patch incomplete: no sv_panel_logout"; exit 1; }
grep -q 'device-rename' "$TMP/silent-api" || { echo "patch incomplete: no device-rename"; exit 1; }
grep -q 'sv-panel-session' "$TMP/web/app.js" || { echo "patch incomplete: no panel session gate"; exit 1; }
grep -q 'device-rename' "$TMP/web/app.js" || { echo "patch incomplete: no rename UI"; exit 1; }
grep -q 'touch-action: pan-y' "$TMP/web/app.css" || { echo "patch incomplete: no nav scroll"; exit 1; }

cp -a /usr/lib/silent-vpn/session.sh "$BK/session.sh" 2>/dev/null || true
cp -a /usr/lib/silent-vpn/hive.sh "$BK/hive.sh" 2>/dev/null || true
cp -a /usr/sbin/silent-vpn-ctl "$BK/silent-vpn-ctl" 2>/dev/null || true
cp -a /www/cgi-bin/silent-api "$BK/silent-api" 2>/dev/null || true
cp -a /www/silent-vpn/index.html "$BK/web/index.html" 2>/dev/null || true
cp -a /www/silent-vpn/js/app.js "$BK/web/app.js" 2>/dev/null || true
cp -a /www/silent-vpn/js/api.js "$BK/web/api.js" 2>/dev/null || true
cp -a /www/silent-vpn/css/app.css "$BK/web/app.css" 2>/dev/null || true

cp "$TMP/session.sh" /usr/lib/silent-vpn/session.sh
chmod 644 /usr/lib/silent-vpn/session.sh
cp "$TMP/hive.sh" /usr/lib/silent-vpn/hive.sh
chmod 644 /usr/lib/silent-vpn/hive.sh
cp "$TMP/silent-vpn-ctl" /usr/sbin/silent-vpn-ctl
chmod 755 /usr/sbin/silent-vpn-ctl
cp "$TMP/silent-api" /www/cgi-bin/silent-api
chmod 755 /www/cgi-bin/silent-api

mkdir -p /www/silent-vpn/js /www/silent-vpn/css
cp "$TMP/web/index.html" /www/silent-vpn/index.html
cp "$TMP/web/app.js" /www/silent-vpn/js/app.js
cp "$TMP/web/api.js" /www/silent-vpn/js/api.js
cp "$TMP/web/app.css" /www/silent-vpn/css/app.css
chmod 644 /www/silent-vpn/index.html /www/silent-vpn/js/app.js /www/silent-vpn/js/api.js /www/silent-vpn/css/app.css

echo "VERSION=$(cat /usr/lib/silent-vpn/VERSION 2>/dev/null || echo unknown)"
echo "has_panel_logout=$(grep -c sv_panel_logout /usr/lib/silent-vpn/session.sh)"
echo "has_device_rename=$(grep -c device-rename /www/cgi-bin/silent-api)"
echo "cache=$(grep -o '1\.0\.170-r[0-9]*' /www/silent-vpn/index.html | head -n1)"
echo "backup=$BK"
echo "ok: panel session patch applied, VPN not restarted"
