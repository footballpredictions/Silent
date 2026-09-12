# Optional WDTT cloak next to WireGuard (same role as wdtt-client on PC).
# Binary is dropped in by the packager; this file only supervises it.

. "$SV_LIB/common.sh"

SV_CLOAK_BIN="${SV_CLOAK_BIN:-/usr/bin/wdtt-client}"
SV_CLOAK_PID="$SV_RUN/cloak.pid"

sv_cloak_available() {
	[ -x "$SV_CLOAK_BIN" ]
}

sv_cloak_stop() {
	if [ -f "$SV_CLOAK_PID" ]; then
		kill "$(cat "$SV_CLOAK_PID")" >/dev/null 2>&1 || true
		rm -f "$SV_CLOAK_PID"
	fi
	killall wdtt-client >/dev/null 2>&1 || true
}

sv_cloak_start() {
	local cfg="$1" pass hashes n
	sv_cloak_available || return 0
	pass="$(jsonfilter -i "$cfg" -e '@.wdtt_password')"
	hashes="$(jsonfilter -i "$cfg" -e '@.vk_hashes[0]')"
	n="$(jsonfilter -i "$cfg" -e '@.stream_count')"
	[ -n "$n" ] || n=9
	sv_cloak_stop
	if [ -z "$pass" ]; then
		sv_log "cloak: no wdtt_password in config, skip"
		return 0
	fi
	# Flags follow the Linux helper contract; extra unknown flags are ignored by older bins.
	"$SV_CLOAK_BIN" \
		-password "$pass" \
		-hash "$hashes" \
		-n "$n" \
		>/var/log/silent-cloak.log 2>&1 &
	echo $! > "$SV_CLOAK_PID"
	sv_log "cloak started pid=$(cat "$SV_CLOAK_PID")"
}
