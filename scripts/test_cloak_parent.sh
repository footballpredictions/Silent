#!/bin/sh
# Integration regression on an idle router. Real spass + BusyBox ash, no LAN
# routes. Requires a private config file already fetched by sv_hive_config.
# Usage: SV_LIB=/tmp/staged-libs sh test_cloak_parent.sh /path/to/private-config
set -eu
SV_LIB="${SV_LIB:-/usr/lib/silent-vpn}"
export SV_LIB
. "$SV_LIB/cloak.sh"
[ ! -f "$SV_RUN/connected" ] || { echo 'Run only with router VPN disconnected' >&2; exit 1; }
[ -s "${1:-}" ] || { echo 'A private config file is required' >&2; exit 1; }
command -v pidof >/dev/null
[ -z "$(pidof spass 2>/dev/null || true)" ] || { echo 'Transport is already running' >&2; exit 1; }
trap 'sv_cloak_stop' EXIT HUP INT TERM
# The request shell returns immediately, exactly like CGI. Do not source
# and launch directly in this longer-lived test shell: that hides the bug.
sh -c '. "$SV_LIB/cloak.sh"; sv_cloak_start "$1"' sh "$1"
sleep 3
wrapper="$(cat "$SV_CLOAK_PID")"
kill -0 "$wrapper" 2>/dev/null || { echo 'FAIL: wrapper died after CGI returned'; exit 1; }
child="$(pidof spass 2>/dev/null || true)"
[ -n "$child" ] || { echo 'FAIL: transport died after CGI returned'; exit 1; }
for pid in $child; do
    parent="$(awk '/^PPid:/ {print $2}' "/proc/$pid/status")"
    [ "$parent" = "$wrapper" ] || { echo 'FAIL: unstable transport parent'; exit 1; }
done
sv_cloak_stop
sleep 1
[ -z "$(pidof spass 2>/dev/null || true)" ] || { echo 'FAIL: transport survived stop'; exit 1; }
[ ! -f "$SV_CLOAK_PID" ] || { echo 'FAIL: stale wrapper marker'; exit 1; }
echo 'PASS: CGI return keeps transport alive; stop removes child and wrapper'
