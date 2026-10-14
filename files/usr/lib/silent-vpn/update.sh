# Panel OTA: fixed server paths, verified architecture package, bounded RAM staging.

sv_update_state() {
	local phase="$1" detail="${2:-}" version="${3:-}"
	# All text is local, never interpolated from a server error/body.
	printf '{"phase":"%s","detail":"%s","version":"%s"}\n' "$phase" "$detail" "$version" > "$SV_RUN/update-state.tmp"
	mv "$SV_RUN/update-state.tmp" "$SV_RUN/update-state.json"
}

sv_update_busy() {
	local pid modified
	[ -d "$SV_RUN/update.lock" ] || return 1
	pid="$(cat "$SV_RUN/update.lock/pid" 2>/dev/null)"
	case "$pid" in ''|*[!0-9]*)
		# Another CGI may see mkdir before the owner has written its PID.
		modified="$(stat -c %Y "$SV_RUN/update.lock" 2>/dev/null)"
		case "$modified" in ''|*[!0-9]*) return 0 ;; esac
		[ "$(( $(date +%s) - modified ))" -lt 60 ]
		return $? ;;
	esac
	kill -0 "$pid" 2>/dev/null
}

sv_update_status() {
	if [ -f "$SV_RUN/update-state.json" ]; then
		if ! sv_update_busy; then
			case "$(sv_json_get "$SV_RUN/update-state.json" phase)" in
				queued|checking|downloading|verifying|installing)
					sv_update_state error 'Обновление прервано. Повторите попытку.' ;;
			esac
		fi
		cat "$SV_RUN/update-state.json"
	else
		echo '{"phase":"idle"}'
	fi
}

sv_update_newer() {
	awk -v latest="$1" -v current="$SV_VERSION" 'BEGIN {
		n=split(latest,a,"."); m=split(current,b,".");
		for(i=1;i<=n || i<=m;i++) { if(a[i]+0>b[i]+0) exit 0; if(a[i]+0<b[i]+0) exit 1 }
		exit 1
	}'
}

sv_update_valid_info() {
	local file="$1" arch="$2" version size unpacked sha
	version="$(sv_json_get "$file" version)"
	echo "$version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || return 1
	sv_update_newer "$version" || return 1
	[ "$(sv_json_get "$file" arch)" = "$arch" ] || return 1
	size="$(sv_json_get "$file" size)"
	unpacked="$(sv_json_get "$file" unpacked_size)"
	case "$size:$unpacked" in *[!0-9:]*|:*|*:) return 1 ;; esac
	[ "$size" -gt 0 ] && [ "$unpacked" -gt 0 ] || return 1
	sha="$(sv_json_get "$file" sha256)"
	[ "${#sha}" = 64 ] || return 1
	case "$sha" in *[!0-9a-f]*) return 1 ;; esac
}

sv_update_info() {
	local arch="$1" out="$2" base code temporary pages
	temporary="$(mktemp "${UPDATE_STAGE:-$SV_RUN}/update-check.XXXXXX")" || return 1
	for base in $(sv_api_bases); do
		code="$(sv_hive_wget GET "$base/api/updates/check?platform=openwrt&version=$SV_VERSION&arch=$arch" '' "$temporary" 6)"
		if [ "$code" = 200 ]; then
			if [ "$(sv_json_get "$temporary" available)" = false ]; then
				rm -f "$temporary"
				return 2
			fi
			if sv_update_valid_info "$temporary" "$arch"; then
				mv "$temporary" "$out"
				return 0
			fi
		fi
	done
	# Public metadata also works before the optional server fields are deployed.
	pages="$(mktemp "${UPDATE_STAGE:-$SV_RUN}/update-pages.XXXXXX")" || { rm -f "$temporary"; return 1; }
	if wget -qO "$pages" --timeout=12 "https://silentvpn3.github.io/releases.json?check=$(date +%s)"; then
		jsonfilter -i "$pages" -e "@.openwrt.arches.$arch" > "$temporary"
		# Pages entries are keyed by architecture, unlike the API response.
		if [ -s "$temporary" ]; then
			printf '{"arch":"%s","available":true,' "$arch" > "$out"
			sed '1s/^[[:space:]]*{//' "$temporary" >> "$out"
			if sv_update_valid_info "$out" "$arch"; then
				rm -f "$temporary" "$pages"
				return 0
			fi
			if [ "$(sv_json_get "$out" version)" = "$SV_VERSION" ]; then
				rm -f "$temporary" "$pages" "$out"
				return 2
			fi
		fi
	fi
	rm -f "$temporary" "$pages" "$out"
	return 1
}

sv_update_check() {
	local slot result info
	sv_update_busy && { sv_update_status; return; }
	slot="$(sv_slot)"
	[ -n "$slot" ] || { echo '{"phase":"error","detail":"Процессор не поддерживается"}'; return; }
	UPDATE_STAGE="$(mktemp -d "$SV_RUN/sv-check.XXXXXX")" || { echo '{"phase":"error","detail":"Недостаточно места для проверки обновления"}'; return; }
	trap '[ -z "$UPDATE_STAGE" ] || rm -rf "$UPDATE_STAGE"' EXIT
	trap 'exit 1' HUP INT TERM
	info="$UPDATE_STAGE/info.json"
	sv_update_info "$slot" "$info"; result=$?
	case "$result" in
		0) printf '{"phase":"available","version":"%s"}\n' "$(sv_json_get "$info" version)" ;;
		2) echo '{"phase":"current"}' ;;
		*) echo '{"phase":"error","detail":"Не удалось проверить обновление. Повторите попытку."}' ;;
	esac
	rm -rf "$UPDATE_STAGE"
	UPDATE_STAGE=""
}

sv_update_start() {
	local launcher_pid worker_pid attempt
	sv_update_busy && { sv_update_status; return; }
	if ! mkdir "$SV_RUN/update.lock" 2>/dev/null; then
		if sv_update_busy; then sv_update_status; return; fi
		# Only one request may reclaim a dead worker's lock.
		mkdir "$SV_RUN/update.lock/reclaim" 2>/dev/null || { sv_update_status; return; }
		if sv_update_busy; then
			rmdir "$SV_RUN/update.lock/reclaim" 2>/dev/null || true
			sv_update_status
			return
		fi
		rm -rf "$SV_RUN/update.lock"
		mkdir "$SV_RUN/update.lock" 2>/dev/null || { sv_update_status; return; }
	fi
	# Ignore the CGI's hangup using POSIX shell builtins; nohup is not in base OpenWrt.
	echo "$$" > "$SV_RUN/update.lock/pid"
	sv_update_state queued 'Подготовка обновления'
	(
		trap '' HUP
		exec /usr/sbin/silent-vpn-update run
	) </dev/null >/dev/null 2>&1 &
	launcher_pid=$!
	# Never overwrite the PID written by the worker, and acknowledge real startup.
	for attempt in 1 2 3 4 5; do
		if [ -f "$SV_RUN/update.lock/started" ] && sv_update_busy; then
			sv_update_status
			return
		fi
		[ -d "$SV_RUN/update.lock" ] || { sv_update_status; return; }
		worker_pid="$(cat "$SV_RUN/update.lock/pid" 2>/dev/null)"
		if [ "$worker_pid" = "$$" ] && ! kill -0 "$launcher_pid" 2>/dev/null; then break; fi
		sleep 1
	done
	kill "$launcher_pid" 2>/dev/null || true
	wait "$launcher_pid" 2>/dev/null || true
	rm -rf "$SV_RUN/update.lock"
	sv_update_state error 'Не удалось запустить обновление. Повторите попытку.'
	sv_update_status
}

sv_update_download() {
	local info="$1" out="$2" arch="$3" base url sha
	sha="$(sv_json_get "$info" sha256)"
	for base in $(sv_api_bases); do
		if wget -qO "$out" --timeout=30 "$base/api/updates/download/openwrt?arch=$arch" &&
			printf '%s  %s\n' "$sha" "$out" | sha256sum -c - >/dev/null 2>&1; then return 0; fi
	done
	url="$(sv_json_get "$info" download_url)"
	case "$url" in https://github.com/silentvpn3/silentvpn3.github.io/releases/download/*) ;; *) return 1 ;; esac
	wget -qO "$out" --timeout=30 "$url" &&
		printf '%s  %s\n' "$sha" "$out" | sha256sum -c - >/dev/null 2>&1
}

sv_update_archive_headers() {
	local archive="$1" slot="$2" version="$3" names
	names="$(tar -tzf "$archive")" || return 1
	printf '%s\n' "$names" | awk '
		$0 !~ /^silent-vpn\// || $0 ~ /(^|\/)\.\.(\/|$)/ {bad=1}
		END {exit bad}' || return 1
	[ "$(tar -xOzf "$archive" silent-vpn/ARCH 2>/dev/null)" = "$slot" ] || return 1
	[ "$(tar -xOzf "$archive" silent-vpn/VERSION 2>/dev/null)" = "$version" ] || return 1
	printf '%s\n' "$names" | grep -qx 'silent-vpn/install.sh' || return 1
	printf '%s\n' "$names" | grep -qx "silent-vpn/files/usr/lib/silent-vpn/wdtt/wdtt-client.$slot"
}

sv_update_archive() {
	local archive="$1" stage="$2" slot="$3" version="$4"
	sv_update_archive_headers "$archive" "$slot" "$version" || return 1
	sv_unpack "$archive" "$stage" || return 1
	[ "$(cat "$stage/silent-vpn/ARCH" 2>/dev/null)" = "$slot" ] || return 1
	[ "$(cat "$stage/silent-vpn/VERSION" 2>/dev/null)" = "$version" ] || return 1
	[ -s "$stage/silent-vpn/install.sh" ] &&
		[ -s "$stage/silent-vpn/files/usr/lib/silent-vpn/wdtt/wdtt-client.$slot" ]
}

sv_update_release_payload() {
	[ -z "${UPDATE_STAGE:-}" ] || rm -rf "$UPDATE_STAGE"
	UPDATE_STAGE=""
}

sv_update_cleanup() {
	sv_update_release_payload
	if [ "${UPDATE_RESUME:-0}" = 1 ]; then
		/etc/init.d/silent-vpn-policy start >/dev/null 2>&1 || true
		silent-vpn-ctl connect >/dev/null 2>&1 || sv_update_state error 'Обновление не завершено. Включите VPN вручную.'
	fi
	rm -rf "$SV_RUN/update.lock"
}

sv_update_run() {
	local slot info version result was_connected backup_bytes size unpacked
	UPDATE_RESUME=0
	echo "$$" > "$SV_RUN/update.lock/pid"
	UPDATE_STAGE="$(mktemp -d /tmp/sv-update.XXXXXX)" || { sv_update_state error 'Не удалось создать временный каталог'; rm -rf "$SV_RUN/update.lock"; return 1; }
	trap sv_update_cleanup EXIT
	trap 'sv_update_state error "Обновление прервано"; exit 1' HUP INT TERM
	sv_update_state checking 'Проверка обновления'
	: > "$SV_RUN/update.lock/started"
	slot="$(sv_slot)"
	[ -n "$slot" ] || { sv_update_state error 'Процессор не поддерживается'; return 1; }
	info="$UPDATE_STAGE/info.json"
	sv_update_info "$slot" "$info"; result=$?
	[ "$result" != 2 ] || { sv_update_state current 'Установлена последняя версия'; return 0; }
	[ "$result" = 0 ] || { sv_update_state error 'Не удалось получить обновление'; return 1; }
	version="$(sv_json_get "$info" version)"
	size="$(sv_json_get "$info" size)"
	unpacked="$(sv_json_get "$info" unpacked_size)"
	# The active VPN only needs room for the compressed download, not two payloads.
	sv_preflight "$size" 1 && sv_space /usr "$(( (unpacked + 1023) / 1024 + 8192 ))" 'установка' || {
		sv_update_state error 'Недостаточно свободного места или памяти'; return 1;
	}
	sv_update_state downloading 'Скачивание обновления' "$version"
	sv_update_download "$info" "$UPDATE_STAGE/package.tgz" "$slot" || {
		sv_update_state error 'Не удалось скачать и проверить пакет. Повторите попытку.'; return 1;
	}
	sv_update_state verifying 'Проверка пакета' "$version"
	sv_update_archive_headers "$UPDATE_STAGE/package.tgz" "$slot" "$version" || {
		sv_update_state error 'Пакет не соответствует версии или процессору'; return 1;
	}
	# Pause only after SHA256, archive structure, architecture and version are valid.
	was_connected=0
	sv_session_connected && was_connected=1
	UPDATE_RESUME="$was_connected"
	sv_update_state verifying 'Подготовка установки' "$version"
	silent-vpn-ctl disconnect >/dev/null 2>&1 || true
	/etc/init.d/silent-vpn-policy stop >/dev/null 2>&1 || true
	backup_bytes="$(du -sk /usr/lib/silent-vpn /usr/bin/spass /www/silent-vpn /usr/sbin/silent-vpn-* /etc/config/silent-vpn 2>/dev/null | awk '{sum+=$1} END {printf "%.0f", sum*1024+65536}')"
	sv_preflight "$size" "$unpacked" "$backup_bytes" || {
		sv_update_state error 'Недостаточно свободного места или памяти'; return 1;
	}
	sv_update_archive "$UPDATE_STAGE/package.tgz" "$UPDATE_STAGE" "$slot" "$version" || {
		sv_update_state error 'Пакет не соответствует версии или процессору'; return 1;
	}
	rm -f "$UPDATE_STAGE/package.tgz"
	# Preserve all existing configuration and executable files before touching VPN.
	(cd / && tar -cf "$UPDATE_STAGE/rollback.tar" usr/lib/silent-vpn usr/bin/spass \
		usr/sbin/silent-vpn-ctl usr/sbin/silent-vpn-policy usr/sbin/silent-vpn-update \
		usr/sbin/silent-vpn-uninstall www/silent-vpn www/cgi-bin/silent-api www/cgi-bin/silent-entry \
		etc/config/silent-vpn etc/init.d/silent-vpn etc/init.d/silent-vpn-policy \
		etc/hotplug.d/iface/99-silent-vpn etc/uci-defaults/99-silent-vpn) || {
		sv_update_state error 'Не удалось сохранить предыдущую сборку'; return 1;
	}
	sv_update_state installing 'Установка обновления' "$version"
	cp /etc/config/silent-vpn "$UPDATE_STAGE/config.before" || { sv_update_state error 'Не удалось сохранить настройки'; return 1; }
	if ! SILENT_OPENWRT_UPDATE=1 sh "$UPDATE_STAGE/silent-vpn/install.sh" --skip-deps >/dev/null 2>&1 ||
		[ "$(cat /usr/lib/silent-vpn/VERSION 2>/dev/null)" != "$version" ]; then
		if ! tar -xf "$UPDATE_STAGE/rollback.tar" -C / >/dev/null 2>&1; then
			UPDATE_RESUME=0
			sv_update_state error 'Ошибка восстановления. Нужна переустановка по инструкции.'
			return 1
		fi
		/etc/init.d/silent-vpn-policy start >/dev/null 2>&1 || true
		UPDATE_RESUME=0
		sv_update_release_payload
		[ "$was_connected" = 0 ] || silent-vpn-ctl connect >/dev/null 2>&1 || true
		sv_update_state error 'Установка не завершена. Восстановлена предыдущая сборка.'
		return 1
	fi
	cp "$UPDATE_STAGE/config.before" /etc/config/silent-vpn
	uci -q set "silent-vpn.main.app_version=$version"
	uci -q commit silent-vpn
	/etc/init.d/silent-vpn-policy restart >/dev/null 2>&1 || true
	UPDATE_RESUME=0
	# Give the transport its RAM back before starting it, while retaining the lock.
	sv_update_release_payload
	if [ "$was_connected" = 1 ] && ! silent-vpn-ctl connect >/dev/null 2>&1; then
		sv_update_state done 'Обновлено. Подключите VPN кнопкой включения.' "$version"
	else
		sv_update_state done 'Обновление установлено' "$version"
	fi
}
