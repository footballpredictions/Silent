#!/bin/sh
# Hot-patch panel LAN access (DSA lan1 + clear 403 text). No VERSION bump, no VPN restart.
# Run on the router. Expects files already in /tmp/sv-lan-patch/ or downloads from $1.

set -e
BASE="${1:-}"
TMP="/tmp/sv-lan-patch"
BK="/tmp/sv-lan-patch-backup-$$"
need="common.sh silent-api silent-entry"

mkdir -p "$TMP" "$BK"
if [ -n "$BASE" ]; then
	for f in $need; do
		wget -qO "$TMP/$f" "$BASE/$f" || { echo "download failed: $f"; exit 1; }
	done
fi

for f in $need; do
	[ -s "$TMP/$f" ] || { echo "missing $TMP/$f"; exit 1; }
done

# Strip Windows CRLF if any
for f in $need; do
	tr -d '\r' < "$TMP/$f" > "$TMP/$f.lf"
	mv "$TMP/$f.lf" "$TMP/$f"
done

sh -n "$TMP/common.sh"
sh -n "$TMP/silent-api"
sh -n "$TMP/silent-entry"
grep -q sv_dev_is_lan "$TMP/common.sh" || { echo "patch incomplete: no sv_dev_is_lan"; exit 1; }
grep -q sv_addr_in_lan_subnet "$TMP/common.sh" || { echo "patch incomplete: no sv_addr_in_lan_subnet"; exit 1; }

cp -a /usr/lib/silent-vpn/common.sh "$BK/common.sh" 2>/dev/null || true
cp -a /www/cgi-bin/silent-api "$BK/silent-api" 2>/dev/null || true
cp -a /www/cgi-bin/silent-entry "$BK/silent-entry" 2>/dev/null || true

# BusyBox OpenWrt often has no `install` applet — use cp/chmod.
cp "$TMP/common.sh" /usr/lib/silent-vpn/common.sh
chmod 644 /usr/lib/silent-vpn/common.sh
cp "$TMP/silent-api" /www/cgi-bin/silent-api
chmod 755 /www/cgi-bin/silent-api
cp "$TMP/silent-entry" /www/cgi-bin/silent-entry
chmod 755 /www/cgi-bin/silent-entry

echo "VERSION=$(cat /usr/lib/silent-vpn/VERSION 2>/dev/null || echo unknown)"
echo "has_sv_dev_is_lan=$(grep -c sv_dev_is_lan /usr/lib/silent-vpn/common.sh)"
echo "backup=$BK"
echo "ok: panel LAN access patched, VPN not restarted"
