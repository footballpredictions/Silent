# Session + connect orchestration.

. "$SV_LIB/common.sh"
. "$SV_LIB/hive.sh"
. "$SV_LIB/path.sh"
. "$SV_LIB/cloak.sh"

sv_session_clear() {
	rm -f "$SV_VAR/access_token" "$SV_VAR/refresh_token" "$SV_VAR/email" "$SV_RUN/connected"
	sv_path_clear
	sv_cloak_stop
}

# Leave the WireGuard tunnel up; only drop Hive tokens so the web UI needs a password again.
sv_panel_logout() {
	rm -f "$SV_VAR/access_token" "$SV_VAR/refresh_token" "$SV_VAR/email"
}

sv_session_active() {
	[ -s "$SV_VAR/access_token" ]
}

sv_session_connected() {
	local pid
	[ -f "$SV_RUN/connected" ] && [ -f "$SV_RUN/path.up" ] || return 1
	sv_tunnel_api_ready || return 1
	pid="$(cat "$SV_RUN/cloak.pid" 2>/dev/null)"
	case "$pid" in ''|*[!0-9]*|0) return 1 ;; esac
	kill -0 "$pid" 2>/dev/null
}

sv_connect_abort() {
	sv_log "$1"
	# Remove LAN policy before stopping transport, including partial startup.
	sv_path_clear
	sv_cloak_stop
	rm -f "$SV_RUN/connected"
	return 1
}

sv_connect_full() {
	local cfg
	sv_log "----- connect -----"
	rm -f "$SV_RUN/bootstrap"
	cfg="$(sv_hive_register_device)"
	if ! jsonfilter -i "$cfg" -e '@.wg_private_key' >/dev/null 2>&1; then
		sv_log "register: no tunnel key, asking config"
		cfg="$(sv_hive_config)"
	fi
	if jsonfilter -i "$cfg" -e '@.wg_private_key' >/dev/null 2>&1; then
		sv_log "config: key yes, server $(jsonfilter -i "$cfg" -e '@.server_ip' 2>/dev/null):$(jsonfilter -i "$cfg" -e '@.server_port' 2>/dev/null)"
	else
		sv_connect_abort "config: no key, connect stopped"
		return 1
	fi
	jsonfilter -i "$cfg" -e '@.device_id' > "$SV_VAR/device_id" 2>/dev/null || true
	sv_cloak_start "$cfg" || { sv_connect_abort "cloak start failed"; return 1; }
	sv_cloak_wait || { sv_connect_abort "cloak wait failed"; return 1; }
	sv_path_up_from_json "$cfg" || { sv_connect_abort "path failed"; return 1; }
	. "$SV_LIB/ru-direct.sh"
	sv_ru_apply || { sv_connect_abort "ru-direct apply failed"; return 1; }
	sv_hive_connect >/dev/null || true
	touch "$SV_RUN/connected"
	sv_log "connect ok"
}

sv_disconnect_full() {
	sv_log "----- disconnect -----"
	sv_hive_disconnect >/dev/null || true
	sv_path_clear
	sv_cloak_stop
	rm -f "$SV_RUN/connected"
	sv_log "path down"
}
