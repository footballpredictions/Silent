# Shared helpers for Silent VPN on OpenWrt. Sourced, not executed.

SV_LIB="${SV_LIB:-/usr/lib/silent-vpn}"
SV_VAR="${SV_VAR:-/etc/silent-vpn}"
SV_RUN="${SV_RUN:-/var/run/silent-vpn}"
SV_CONF="${SV_CONF:-/etc/config/silent-vpn}"
SV_VERSION="${SV_VERSION:-1.0.167}"
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
	logger -t silent-vpn "$*"
}

sv_uci_get() {
	uci -q get "silent-vpn.$1" 2>/dev/null || true
}

sv_json_get() {
	# usage: sv_json_get FILE key
	jsonfilter -i "$1" -e "@.$2" 2>/dev/null || true
}

sv_is_ipv4() {
	echo "$1" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$' || return 1
	echo "$1" | awk -F. '{
		for (i = 1; i <= 4; i++) if ($i + 0 > 255) exit 1
	}'
}

sv_lan_ip() {
	local ip
	ip="$(uci -q get network.lan.ipaddr 2>/dev/null | awk '{print $1}')"
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

sv_api_bases() {
	# VPN поднят — только шлюз туннеля. Иначе соты :9100, Улей :443 последним.
	if [ -f "$SV_RUN/path.up" ]; then
		echo "$SV_TUNNEL_API"
		return
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

# 0 = allow Silent UI (cable / local). 1 = Wi-Fi client, refuse.
sv_http_allow_wired() {
	local addr="${REMOTE_ADDR:-}"
	case "$addr" in
		""|127.*|::1|::ffff:127.*) return 0 ;;
	esac
	if sv_addr_is_wifi_client "$addr"; then
		return 1
	fi
	return 0
}

sv_token() {
	cat "$SV_VAR/access_token" 2>/dev/null || true
}

sv_http() {
	# sv_http METHOD PATH [BODY_FILE]
	local method="$1" path="$2" body="${3:-}"
	local url base out hdr token extra to
	out="$(mktemp "$SV_RUN/http.XXXXXX")"
	hdr="$(mktemp "$SV_RUN/hdr.XXXXXX")"
	token="$(sv_token)"
	extra=""
	[ -n "$token" ] && extra="--header=Authorization: Bearer $token"
	for base in $(sv_api_bases); do
		: > "$out"
		url="${base}${path}"
		to="$(sv_hive_timeout_for "$base")"
		if [ -n "$body" ]; then
			wget -qO "$out" --timeout="$to" --server-response \
				--header="Content-Type: application/json" \
				--header="X-App-Version: $SV_VERSION" \
				$extra \
				--post-file="$body" \
				--method="$method" \
				"$url" 2>"$hdr" || true
		else
			wget -qO "$out" --timeout="$to" --server-response \
				--header="X-App-Version: $SV_VERSION" \
				$extra \
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
