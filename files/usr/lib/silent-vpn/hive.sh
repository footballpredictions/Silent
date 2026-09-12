# Talk to Silent hive API. Unique OpenWrt client — same endpoints as PC/Android.

. "$SV_LIB/common.sh"

sv_hive_post() {
	local path="$1" json="$2"
	local tmp out code
	sv_mkdir
	tmp="$(mktemp "$SV_RUN/body.XXXXXX")"
	printf '%s' "$json" > "$tmp"
	out="$(mktemp "$SV_RUN/out.XXXXXX")"
	code="$(sv_hive_wget POST "$(sv_api_base)$path" "$tmp" "$out")"
	echo "$code" > "$SV_RUN/http.code"
	echo "$out"
}

sv_hive_get() {
	local path="$1"
	local out
	sv_mkdir
	out="$(mktemp "$SV_RUN/out.XXXXXX")"
	sv_hive_wget GET "$(sv_api_base)$path" "" "$out" > "$SV_RUN/http.code"
	echo "$out"
}

sv_hive_wget() {
	local method="$1" url="$2" body="$3" out="$4"
	local token args st
	token="$(sv_token)"
	args="-qO $out --timeout=20"
	[ -n "$token" ] && args="$args --header=Authorization: Bearer $token"
	args="$args --header=X-App-Version:\ $SV_VERSION --header=Content-Type: application/json"
	if [ "$method" = "POST" ]; then
		# busybox wget: POST via --post-file
		wget $args --post-file="$body" "$url" >/dev/null 2>&1
		st=$?
	else
		wget $args "$url" >/dev/null 2>&1
		st=$?
	fi
	if [ "$st" -eq 0 ]; then
		echo 200
	else
		echo 000
	fi
}

sv_hive_theme() {
	sv_hive_get "/api/vpn/theme"
}

sv_hive_login() {
	local email="$1" password="$2" out
	out="$(sv_hive_post "/api/auth/login" "$(printf '{"email":"%s","password":"%s"}' "$email" "$password")")"
	if [ -s "$out" ] && jsonfilter -i "$out" -e '@.access_token' >/dev/null; then
		jsonfilter -i "$out" -e '@.access_token' > "$SV_VAR/access_token"
		jsonfilter -i "$out" -e '@.refresh_token' > "$SV_VAR/refresh_token"
		printf '%s' "$email" > "$SV_VAR/email"
		echo "$out"
		return 0
	fi
	echo "$out"
	return 1
}

sv_hive_register() {
	local email="$1" password="$2" code="$3" json
	if [ -n "$code" ]; then
		json="$(printf '{"email":"%s","password":"%s","referral_or_promo":"%s"}' "$email" "$password" "$code")"
	else
		json="$(printf '{"email":"%s","password":"%s"}' "$email" "$password")"
	fi
	sv_hive_post "/api/auth/register" "$json"
}

sv_hive_forgot() {
	sv_hive_post "/api/auth/forgot-password" "$(printf '{"email":"%s"}' "$1")"
}

sv_hive_me() {
	sv_hive_get "/api/users/me"
}

sv_hive_register_device() {
	local fp name json
	fp="$(sv_fingerprint)"
	name="$(sv_device_name)"
	json="$(printf '{"device_name":"%s","device_type":"%s","device_fingerprint":"%s","bootstrap_hash":"%s"}' \
		"$name" "$SV_DEVICE_TYPE" "$fp" "$SV_BOOTSTRAP_HASH")"
	sv_hive_post "/api/vpn/device/register" "$json"
}

sv_hive_config() {
	local fp
	fp="$(sv_fingerprint)"
	sv_hive_get "/api/vpn/config?fingerprint=$fp"
}

sv_hive_connect() {
	local fp json
	fp="$(sv_fingerprint)"
	json="$(printf '{"device_fingerprint":"%s","device_type":"%s"}' "$fp" "$SV_DEVICE_TYPE")"
	sv_hive_post "/api/vpn/connect" "$json"
}

sv_hive_disconnect() {
	local fp json
	fp="$(sv_fingerprint)"
	json="$(printf '{"device_fingerprint":"%s"}' "$fp")"
	sv_hive_post "/api/vpn/disconnect" "$json"
}

sv_hive_preferred() {
	local key="$1" fp json
	fp="$(sv_fingerprint)"
	json="$(printf '{"device_fingerprint":"%s","preferred_server":"%s","app_version":"%s"}' \
		"$fp" "$key" "$SV_VERSION")"
	sv_hive_post "/api/vpn/servers/select" "$json"
}

sv_hive_referral() {
	sv_hive_get "/api/users/me/referral"
}

sv_hive_servers() {
	sv_hive_get "/api/vpn/servers?fingerprint=$(sv_fingerprint)&app_version=$SV_VERSION"
}

sv_hive_pay() {
	sv_hive_post "/api/payments/init" "$(printf '{"plan_type":"%s"}' "$1")"
}
