# Cloak beside WireGuard (same role as on PC). Binary is bundled with the package.

. "$SV_LIB/common.sh"

SV_CLOAK_BIN="${SV_CLOAK_BIN:-/usr/bin/spass}"
SV_CLOAK_PID="$SV_RUN/cloak.pid"

sv_cloak_available() {
	[ -x "$SV_CLOAK_BIN" ]
}

sv_cloak_stop() {
	if [ -f "$SV_CLOAK_PID" ]; then
		kill "$(cat "$SV_CLOAK_PID")" >/dev/null 2>&1 || true
		rm -f "$SV_CLOAK_PID"
	fi
	killall spass >/dev/null 2>&1 || true
	killall svpass >/dev/null 2>&1 || true
	killall svcloak >/dev/null 2>&1 || true
	killall wdtt-client >/dev/null 2>&1 || true
}

sv_cloak_start() {
	local cfg="$1" pass hashes n sip sport did
	sv_cloak_available || return 0
	pass="$(jsonfilter -i "$cfg" -e '@.wdtt_password')"
	hashes="$(jsonfilter -i "$cfg" -e '@.vk_hashes[*]' | tr '\n' ',' | sed 's/,$//')"
	n="$(jsonfilter -i "$cfg" -e '@.stream_count')"
	sip="$(jsonfilter -i "$cfg" -e '@.server_ip')"
	sport="$(jsonfilter -i "$cfg" -e '@.server_port')"
	did="$(jsonfilter -i "$cfg" -e '@.device_id')"
	[ -n "$n" ] || n=9
	sv_cloak_stop
	if [ -z "$pass" ] || [ -z "$hashes" ] || [ -z "$sip" ] || [ -z "$sport" ]; then
		sv_log "cloak: no peer, vk or password in config, skip"
		return 1
	fi
	# spass exits when its parent exits. This shell stays alive so the bypass does too.
	# Flags are the real ones: -peer -vk -listen. -hash is unknown and the process dies at once.
	# cwd is fixed so GETCONF lands in /etc/silent-vpn/wg-turn.conf.
	mkdir -p /etc/silent-vpn
	rm -f /etc/silent-vpn/wg-turn.conf
	(
		trap '' HUP
		cd /etc/silent-vpn || exit 1
		"$SV_CLOAK_BIN" \
			-peer "${sip}:${sport}" \
			-vk "$hashes" \
			-password "$pass" \
			-device-id "$did" \
			-listen 127.0.0.1:9000 \
			-n "$n" \
			>>/var/log/silent-cloak.log 2>&1
	) &
	echo $! > "$SV_CLOAK_PID"
	sv_log "cloak started pid=$(cat "$SV_CLOAK_PID")"
}

sv_cloak_wait() {
	local i=0
	while [ "$i" -lt 25 ]; do
		if netstat -lun 2>/dev/null | grep -q ':9000' || ss -lun 2>/dev/null | grep -q ':9000'; then
			if [ -s /etc/silent-vpn/wg-turn.conf ]; then
				return 0
			fi
		fi
		i=$((i + 1))
		sleep 1
	done
	sv_log "cloak: 127.0.0.1:9000 did not open"
	return 1
}
