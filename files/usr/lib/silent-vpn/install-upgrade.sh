# Manual upgrades use the package's helpers, including when updating old clients.
# Called in a subshell so traps and update-only settings never leak to the caller.
sv_install_upgrade() (
	SV_RUN=/var/run/silent-vpn
	. "$ROOT/files/usr/lib/silent-vpn/update.sh"
	mkdir -p "$SV_RUN"
	if ! mkdir "$SV_RUN/update.lock" 2>/dev/null; then
		if sv_update_busy; then
			echo 'Дождитесь завершения обновления.' >&2
			exit 1
		fi
		mkdir "$SV_RUN/update.lock/reclaim" 2>/dev/null || exit 1
		if sv_update_busy; then
			rmdir "$SV_RUN/update.lock/reclaim" 2>/dev/null || true
			exit 1
		fi
		rm -rf "$SV_RUN/update.lock"
		mkdir "$SV_RUN/update.lock" 2>/dev/null || exit 1
	fi
	echo "$$" > "$SV_RUN/update.lock/pid"
	SV_INSTALL_BACKUP=''
	SV_INSTALL_RESUME=0
	SV_INSTALL_PAUSED=0
	SV_INSTALL_MODIFIED=0
	SV_INSTALL_KEEP_BACKUP=0
	# Only owned program/configuration paths; login files are never replaced.
	SV_INSTALL_PATHS='usr/lib/silent-vpn usr/bin/spass usr/bin/svpass usr/bin/svcloak usr/bin/wdtt-client
usr/sbin/silent-vpn-ctl usr/sbin/silent-vpn-policy usr/sbin/silent-vpn-update usr/sbin/silent-vpn-uninstall
www/silent-vpn www/cgi-bin/silent-api www/cgi-bin/silent-entry etc/config/silent-vpn
etc/init.d/silent-vpn etc/init.d/silent-vpn-policy etc/init.d/silent-vpn-dns
etc/hotplug.d/iface/99-silent-vpn etc/uci-defaults/99-silent-vpn'
	sv_install_upgrade_finish() {
		result=$?
		trap - EXIT HUP INT TERM
		set +e
		if [ "$result" != 0 ] && [ "$SV_INSTALL_MODIFIED" = 1 ]; then
			/etc/init.d/silent-vpn-policy stop >/dev/null 2>&1 || true
			/etc/init.d/silent-vpn-dns stop >/dev/null 2>&1 || true
			# Validate before removing the partial installation, including new files.
			if tar -tf "$SV_INSTALL_BACKUP/rollback.tar" >/dev/null; then
				for path in $SV_INSTALL_PATHS; do rm -rf "/$path"; done
			fi
			if tar -xf "$SV_INSTALL_BACKUP/rollback.tar" -C /; then
				echo 'Установка не завершена. Предыдущая сборка восстановлена.' >&2
			else
				SV_INSTALL_RESUME=0
				SV_INSTALL_KEEP_BACKUP=1
				echo "Не удалось восстановить сборку. Резервная копия: $SV_INSTALL_BACKUP" >&2
			fi
		fi
		if [ -n "$SV_INSTALL_BACKUP" ] && [ "$SV_INSTALL_KEEP_BACKUP" = 0 ]; then
			rm -rf "$SV_INSTALL_BACKUP"
		fi
		# Only the bootstrap's disposable payload may be released here. Leave a
		# manually unpacked source directory alone, and reject nested stage names.
		case "${SILENT_OPENWRT_STAGE:-}" in
			/tmp/sv-install.*)
				case "${SILENT_OPENWRT_STAGE#/tmp/sv-install.}" in
					''|*/*) ;;
					*)
						if [ "$ROOT" = "$SILENT_OPENWRT_STAGE/silent-vpn" ] || [ "$ROOT" = "$SILENT_OPENWRT_STAGE/Silent-openwrt" ]; then
							rm -rf "$ROOT"
						fi ;;
				esac ;;
		esac
		# Release the backup's RAM before reconnecting; keep the update lock until done.
		if [ "$SV_INSTALL_PAUSED" = 1 ]; then
			/etc/init.d/silent-vpn-policy start >/dev/null 2>&1 || true
			if [ "$SV_INSTALL_RESUME" = 1 ]; then
				/usr/sbin/silent-vpn-ctl connect >/dev/null 2>&1 || echo 'Подключите VPN кнопкой включения.' >&2
			fi
		fi
		rm -rf "$SV_RUN/update.lock"
		exit "$result"
	}
	trap sv_install_upgrade_finish EXIT
	trap 'exit 1' HUP INT TERM
	[ "${1:-0}" = 1 ] || install_deps
	SV_INSTALL_BACKUP="$(mktemp -d /tmp/sv-upgrade.XXXXXX)"
	: > "$SV_INSTALL_BACKUP/paths"
	for path in $SV_INSTALL_PATHS; do
		[ ! -e "/$path" ] || printf '%s\n' "$path" >> "$SV_INSTALL_BACKUP/paths"
	done
	needed="$(cd / && du -sk $(cat "$SV_INSTALL_BACKUP/paths") | awk '{n+=$1} END {print n+8192}')"
	free="$(df -Pk /tmp | awk 'END {print $4}')"
	[ "$free" -ge "$needed" ] || { echo 'Недостаточно места для резервной копии.' >&2; exit 1; }
	# Preserve whether the user had VPN on, even when the tunnel is temporarily down.
	[ ! -f "$SV_RUN/connected" ] || SV_INSTALL_RESUME=1
	SV_INSTALL_PAUSED=1
	/etc/init.d/silent-vpn-policy stop >/dev/null 2>&1 || true
	/usr/sbin/silent-vpn-ctl disconnect >/dev/null 2>&1 || true
	/etc/init.d/silent-vpn-dns stop >/dev/null 2>&1 || true
	(cd / && tar -cf "$SV_INSTALL_BACKUP/rollback.tar" $(cat "$SV_INSTALL_BACKUP/paths"))
	SV_INSTALL_MODIFIED=1
	SILENT_OPENWRT_UPDATE=1 install_files
)
