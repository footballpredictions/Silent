# Shared helpers for Silent VPN on OpenWrt. Sourced, not executed.

SV_LIB="${SV_LIB:-/usr/lib/silent-vpn}"
SV_VAR="${SV_VAR:-/etc/silent-vpn}"
SV_RUN="${SV_RUN:-/var/run/silent-vpn}"
SV_CONF="${SV_CONF:-/etc/config/silent-vpn}"
SV_VERSION="${SV_VERSION:-1.0.165}"
SV_DEVICE_TYPE="pc"
SV_PUBLIC_API="${SV_PUBLIC_API:-https://132-243-234-162.nip.io}"
SV_TUNNEL_API="${SV_TUNNEL_API:-http://10.66.66.1:8000}"
SV_BOOTSTRAP_HASH="${SV_BOOTSTRAP_HASH:-4uhJXsVypBdlEbvt6k4hPEFi3RooXUqyUwDG4lgPBDY}"
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

sv_api_base() {
	if [ -f "$SV_RUN/path.up" ]; then
		echo "$SV_TUNNEL_API"
	else
		echo "${SV_API_OVERRIDE:-$SV_PUBLIC_API}"
	fi
}

sv_token() {
	cat "$SV_VAR/access_token" 2>/dev/null || true
}

sv_http() {
	# sv_http METHOD PATH [BODY_FILE]
	local method="$1" path="$2" body="${3:-}"
	local url base out hdr token extra
	base="$(sv_api_base)"
	url="${base}${path}"
	out="$(mktemp "$SV_RUN/http.XXXXXX")"
	hdr="$(mktemp "$SV_RUN/hdr.XXXXXX")"
	token="$(sv_token)"
	extra=""
	[ -n "$token" ] && extra="--header=Authorization: Bearer $token"
	if [ -n "$body" ]; then
		wget -qO "$out" --server-response \
			--header="Content-Type: application/json" \
			--header="X-App-Version: $SV_VERSION" \
			$extra \
			--post-file="$body" \
			--method="$method" \
			"$url" 2>"$hdr" || true
	else
		wget -qO "$out" --server-response \
			--header="X-App-Version: $SV_VERSION" \
			$extra \
			--method="$method" \
			"$url" 2>"$hdr" || true
	fi
	echo "$out"
}
