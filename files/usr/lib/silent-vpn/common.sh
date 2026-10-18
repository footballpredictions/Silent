# Shared helpers for Silent VPN on OpenWrt. Sourced, not executed.

SV_LIB="${SV_LIB:-/usr/lib/silent-vpn}"
SV_VAR="${SV_VAR:-/etc/silent-vpn}"
SV_RUN="${SV_RUN:-/var/run/silent-vpn}"
SV_CONF="${SV_CONF:-/etc/config/silent-vpn}"
SV_VERSION="${SV_VERSION:-1.0.170}"
# The installed payload is authoritative, including after an in-place update.
if [ -r "$SV_LIB/VERSION" ]; then
	SV_VERSION="$(cat "$SV_LIB/VERSION")"
fi
SV_DEVICE_TYPE="pc"
SV_PUBLIC_API="${SV_PUBLIC_API:-https://89-125-188-100.nip.io}"
SV_TUNNEL_API="${SV_TUNNEL_API:-http://10.66.66.1:8000}"
SV_BOOTSTRAP_HASH="${SV_BOOTSTRAP_HASH:-T5oeMQkn6iF1XfUfhxGQ0h6j4lHEoJ5wTGEyi1Q_2cc}"
SV_ZONE="silent.vpn"
SV_WG_IF="svpath"
SV_WG_ZONE="svpath"

sv_mkdir() {
	mkdir -p "$SV_VAR" "$SV_RUN" 2>/dev/null || true
	chmod 700 "$SV_VAR" 2>/dev/null || true
}

sv_log() {
	# Production builds do not write diagnostics to RAM, flash or syslog.
	:
}

sv_uci_get() {
	uci -q get "silent-vpn.$1" 2>/dev/null || true
}

sv_json_get() {
	# usage: sv_json_get FILE key
	jsonfilter -i "$1" -e "@.$2" 2>/dev/null || true
}

sv_is_ipv4() {
	# awk only: busybox grep often has no {1,3} and then apply-dns exits before writing the name
	echo "$1" | awk -F. '{
		if (NF != 4) exit 1
		for (i = 1; i <= 4; i++) if ($i !~ /^[0-9]+$/ || $i + 0 > 255) exit 1
		exit 0
	}'
}

sv_lan_ip() {
	local ip
	ip="$(uci -q get network.lan.ipaddr 2>/dev/null | awk '{print $1}')"
	ip="${ip%%/*}"
	[ -n "$ip" ] || ip="$(ip -4 addr show br-lan 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 | head -n1)"
	[ -n "$ip" ] || ip="192.168.1.1"
	echo "$ip"
}

sv_lan_host() {
	echo "$(sv_lan_ip).$SV_ZONE"
}

sv_lan_url() {
	echo "http://$(sv_lan_host)"
}

sv_fingerprint() {
	local fp
	fp="$(cat "$SV_VAR/fingerprint" 2>/dev/null || true)"
	if [ -n "$fp" ]; then
		echo "$fp"
		return 0
	fi
	sv_mkdir
	fp="$(
		{
			cat /sys/class/net/br-lan/address 2>/dev/null
			cat /etc/board.json 2>/dev/null
			cat /proc/cpuinfo 2>/dev/null | head -n 8
		} | tr -d '\r' | md5sum | awk '{print $1}'
	)"
	echo "$fp" > "$SV_VAR/fingerprint"
	echo "$fp"
}

sv_device_name() {
	# Hive stores this on the session; UI splits "OpenWrt" + router model.
	echo "OpenWrt $(sv_router_name)" | cut -c1-64
}

sv_router_name() {
	local model host
	host="$(uname -n 2>/dev/null || echo openwrt)"
	model="$(jsonfilter -i /etc/board.json -e '@.model.name' 2>/dev/null || true)"
	if [ -n "$model" ]; then
		echo "$model"
	else
		echo "$host"
	fi
}

sv_tunnel_api_ready() {
	[ -f "$SV_RUN/path.up" ] && [ -d "/sys/class/net/$SV_WG_IF" ] || return 1
	ip -4 route get 10.66.66.1 2>/dev/null | awk -v iface="$SV_WG_IF" '
		{for(i=1;i<NF;i++) if($i=="dev" && $(i+1)==iface) found=1}
		END {exit !found}'
}

sv_api_bases() {
	# Prefer a routed tunnel, but keep recovery APIs available after a tunnel failure.
	# wget не подменяет Host для HTTPS по IP: сначала рабочий HTTP-прокси сот.
	if [ -f "$SV_RUN/path.up" ] && sv_tunnel_api_ready; then
		echo "$SV_TUNNEL_API"
	fi
	if [ -n "$SV_API_OVERRIDE" ]; then
		case "$SV_API_OVERRIDE" in
			*132.243.234.162*|*132-243-234-162*) ;;
			*) echo "$SV_API_OVERRIDE"; return ;;
		esac
	fi
	echo "http://87.58.213.193:9100"
	echo "http://78.17.74.27:9100"
	echo "${SV_PUBLIC_API:-https://89-125-188-100.nip.io}"
	echo "https://89.125.188.100"
}

sv_api_base() {
	sv_api_bases | head -n1
}

sv_hive_timeout_for() {
	case "$1" in
		*:9100*) echo 8 ;;
		*10.66.66.1*) echo 8 ;;
		*) echo 4 ;;
	esac
}

sv_neigh_mac() {
	local addr="$1" mac
	addr="$(echo "$addr" | tr 'A-Z' 'a-z')"
	addr="${addr#::ffff:}"
	mac="$(ip -4 neigh show "$addr" 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "lladdr") { print $(i + 1); exit }}')"
	[ -n "$mac" ] || mac="$(awk -v ip="$addr" '$1 == ip { print $4; exit }' /proc/net/arp 2>/dev/null)"
	echo "$mac" | tr 'A-Z' 'a-z'
}

sv_is_wireless_dev() {
	local d="$1"
	[ -n "$d" ] || return 1
	[ -d "/sys/class/net/$d/phy80211" ] && return 0
	[ -d "/sys/class/net/$d/wireless" ] && return 0
	case "$d" in
		wlan*|apcli*|rax*|phy*-ap*|ra[0-9]*|wl[0-9]*|ath[0-9]*) return 0 ;;
	esac
	return 1
}

sv_addr_is_wifi_client() {
	local addr="$1" mac iface ifaces
	addr="$(echo "$addr" | tr 'A-Z' 'a-z')"
	addr="${addr#::ffff:}"
	mac="$(sv_neigh_mac "$addr")"
	[ -n "$mac" ] || return 1
	if command -v iw >/dev/null 2>&1; then
		ifaces="$(iw dev 2>/dev/null | awk '/Interface/{print $2}')"
		for iface in $ifaces; do
			iw dev "$iface" station get "$mac" >/dev/null 2>&1 && return 0
		done
	fi
	for iface in /sys/class/net/*/phy80211; do
		[ -e "$iface" ] || continue
		iface="$(echo "$iface" | sed 's|^/sys/class/net/||;s|/phy80211||')"
		sv_is_wireless_dev "$iface" || continue
		iw dev "$iface" station get "$mac" >/dev/null 2>&1 && return 0
	done
	return 1
}

# True if $1 is the LAN L3 device or a bridge port under it (DSA lan1/lan2, eth0…).
sv_dev_is_lan() {
	local d="$1" lan="$2" master
	[ -n "$d" ] && [ -n "$lan" ] || return 1
	[ "$d" = "$lan" ] && return 0
	[ -e "/sys/class/net/$lan/brif/$d" ] && return 0
	if [ -L "/sys/class/net/$d/master" ]; then
		master="$(basename "$(readlink "/sys/class/net/$d/master" 2>/dev/null)" 2>/dev/null)"
		[ "$master" = "$lan" ] && return 0
	fi
	return 1
}

# Allow devices directly connected to the LAN, over either cable or Wi-Fi.
# Private addresses alone are not enough: guest, WAN and VPN use them too.
# DSA cable ports often appear as "dev lan1" in `ip route get`, not br-lan.
sv_http_allow_lan() {
	local addr family lan_dev route scope dev
	addr="$(printf '%s' "${REMOTE_ADDR:-}" | tr 'A-Z' 'a-z')"
	addr="${addr#::ffff:}"
	[ -n "$addr" ] || return 1
	[ "$addr" = "::1" ] && return 0
	lan_dev="$(ubus call network.interface.lan status 2>/dev/null | jsonfilter -e '@.l3_device' 2>/dev/null)"
	[ -n "$lan_dev" ] || lan_dev="$(uci -q get network.lan.device)"
	if [ -z "$lan_dev" ]; then
		if [ "$(uci -q get network.lan.type)" = bridge ]; then
			lan_dev=br-lan
		else
			lan_dev="$(uci -q get network.lan.ifname)"
		fi
	fi
	lan_dev="${lan_dev:-br-lan}"
	case "$addr" in
		*:*)
			family=-6
			scope="${addr#*%}"
			if [ "$scope" != "$addr" ]; then
				sv_dev_is_lan "$scope" "$lan_dev" || return 1
				addr="${addr%%%*}"
			fi
			case "$addr" in *[!0-9a-f:]*) return 1 ;; esac
			case "$addr" in fe[89ab][0-9a-f]:*) addr="$addr%$lan_dev" ;; esac
			;;
		*)
			family=-4
			sv_is_ipv4 "$addr" || return 1
			case "$addr" in 127.*) return 0 ;; esac
			;;
	esac
	route="$(ip "$family" route get "$addr" 2>/dev/null)" || return 1
	case "$route" in
		*" via "*) return 1 ;;
	esac
	dev="$(printf '%s\n' "$route" | awk '{ for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit } }')"
	sv_dev_is_lan "$dev" "$lan_dev"
}

# Compatibility with already installed CGI files during a small-file upgrade.
sv_http_allow_wired() {
	sv_http_allow_lan
}

sv_token() {
	[ -s "$SV_VAR/access_token" ] || return 0
	tr -d ' \t\r\n' < "$SV_VAR/access_token" 2>/dev/null || true
}

sv_http() {
	# sv_http METHOD PATH [BODY_FILE]
	local method="$1" path="$2" body="${3:-}"
	local url base out hdr token to
	out="$(mktemp "$SV_RUN/http.XXXXXX")"
	hdr="$(mktemp "$SV_RUN/hdr.XXXXXX")"
	token="$(sv_token)"
	for base in $(sv_api_bases); do
		: > "$out"
		url="${base}${path}"
		to="$(sv_hive_timeout_for "$base")"
		# Headers stay quoted. Unquoted expansion splits "Bearer <token>" and the hive sees no login.
		if [ -n "$body" ]; then
			if [ -n "$token" ]; then
				wget -qO "$out" --timeout="$to" --server-response \
					--header="Content-Type: application/json" \
					--header="X-App-Version: $SV_VERSION" \
					--header="Authorization: Bearer $token" \
					--post-file="$body" \
					--method="$method" \
					"$url" 2>"$hdr" || true
			else
				wget -qO "$out" --timeout="$to" --server-response \
					--header="Content-Type: application/json" \
					--header="X-App-Version: $SV_VERSION" \
					--post-file="$body" \
					--method="$method" \
					"$url" 2>"$hdr" || true
			fi
		elif [ -n "$token" ]; then
			wget -qO "$out" --timeout="$to" --server-response \
				--header="X-App-Version: $SV_VERSION" \
				--header="Authorization: Bearer $token" \
				--method="$method" \
				"$url" 2>"$hdr" || true
		else
			wget -qO "$out" --timeout="$to" --server-response \
				--header="X-App-Version: $SV_VERSION" \
				--method="$method" \
				"$url" 2>"$hdr" || true
		fi
		if [ -s "$out" ]; then
			echo "$out"
			return
		fi
	done
	echo "$out"
}
