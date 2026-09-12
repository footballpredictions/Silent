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

sv_session_active() {
	[ -s "$SV_VAR/access_token" ]
}

sv_connect_full() {
	local cfg
	rm -f "$SV_RUN/bootstrap"
	cfg="$(sv_hive_register_device)"
	if ! jsonfilter -i "$cfg" -e '@.wg_private_key' >/dev/null; then
		cfg="$(sv_hive_config)"
	fi
	jsonfilter -i "$cfg" -e '@.device_id' > "$SV_VAR/device_id" 2>/dev/null || true
	sv_path_up_from_json "$cfg" || return 1
	. "$SV_LIB/ru-direct.sh"
	sv_ru_apply
	sv_cloak_start "$cfg"
	sv_hive_connect >/dev/null || true
	touch "$SV_RUN/connected"
	sv_log "path up"
}

sv_disconnect_full() {
	sv_hive_disconnect >/dev/null || true
	sv_cloak_stop
	sv_path_clear
	rm -f "$SV_RUN/connected"
	sv_log "path down"
}
