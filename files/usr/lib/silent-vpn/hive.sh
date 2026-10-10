# Talk to Silent hive API. Unique OpenWrt client — same endpoints as PC/Android.

. "$SV_LIB/common.sh"

sv_hive_post() {
	local path="$1" json="$2"
	local tmp out code base to
	sv_mkdir
	tmp="$(mktemp "$SV_RUN/body.XXXXXX")"
	printf '%s' "$json" > "$tmp"
	out="$(mktemp "$SV_RUN/out.XXXXXX")"
	code="000"
	for base in $(sv_api_bases); do
		: > "$out"
		to="$(sv_hive_timeout_for "$base")"
		code="$(sv_hive_wget POST "${base}${path}" "$tmp" "$out" "$to")"
		if [ -s "$out" ]; then
			break
		fi
	done
	echo "$code" > "$SV_RUN/http.code"
	echo "$out"
}

sv_hive_get() {
	local path="$1"
	local out code base to
	sv_mkdir
	out="$(mktemp "$SV_RUN/out.XXXXXX")"
	code="000"
	for base in $(sv_api_bases); do
		: > "$out"
		to="$(sv_hive_timeout_for "$base")"
		code="$(sv_hive_wget GET "${base}${path}" "" "$out" "$to")"
		if [ -s "$out" ]; then
			break
		fi
	done
	echo "$code" > "$SV_RUN/http.code"
	echo "$out"
}

sv_hive_wget() {
	local method="$1" url="$2" body="$3" out="$4" timeout="${5:-20}"
	local token st errf err code
	token="$(sv_token)"
	errf="$(mktemp "$SV_RUN/wget.XXXXXX")"
	# One quoted header. `wget $args` splits "Bearer <token>" into extra words, so /me comes back unsigned.
	# stderr is kept: uclient-fetch drops the body on HTTP 4xx, and the status is only in that line.
	if [ "$method" = "POST" ]; then
		if [ -n "$token" ]; then
			wget -O "$out" --timeout="$timeout" \
				--header="Content-Type: application/json" \
				--header="X-App-Version: $SV_VERSION" \
				--header="Authorization: Bearer $token" \
				--post-file="$body" \
				"$url" >"$errf" 2>&1
		else
			wget -O "$out" --timeout="$timeout" \
				--header="Content-Type: application/json" \
				--header="X-App-Version: $SV_VERSION" \
				--post-file="$body" \
				"$url" >"$errf" 2>&1
		fi
		st=$?
	elif [ -n "$token" ]; then
		wget -O "$out" --timeout="$timeout" \
			--header="X-App-Version: $SV_VERSION" \
			--header="Authorization: Bearer $token" \
			"$url" >"$errf" 2>&1
		st=$?
	else
		wget -O "$out" --timeout="$timeout" \
			--header="X-App-Version: $SV_VERSION" \
			"$url" >"$errf" 2>&1
		st=$?
	fi
	err="$(cat "$errf" 2>/dev/null || true)"
	rm -f "$errf"
	if [ "$st" -eq 0 ]; then
		echo 200
		return
	fi
	code="$(printf '%s\n' "$err" | sed -n 's/.*[^0-9]\([1-5][0-9][0-9]\).*/\1/p' | head -n 1)"
	case "$code" in
		401)
			[ -s "$out" ] || printf '%s\n' '{"detail":"Неверный email или пароль"}' > "$out"
			echo 401
			;;
		4*|5*)
			[ -s "$out" ] || printf '%s\n' "{\"detail\":\"Сервер ответил ${code}\"}" > "$out"
			echo "$code"
			;;
		*)
			echo 000
			;;
	esac
}

sv_hive_theme() {
	sv_hive_get "/api/vpn/theme"
}

sv_hive_login() {
	local email="$1" password="$2" out token
	out="$(sv_hive_post "/api/auth/login" "$(printf '{"email":"%s","password":"%s"}' "$email" "$password")")"
	token="$(jsonfilter -i "$out" -e '@.access_token' 2>/dev/null || true)"
	# A real session token has three parts. An error body must not keep the previous login.
	case "$token" in
		*.*.*)
			printf '%s' "$token" > "$SV_VAR/access_token"
			jsonfilter -i "$out" -e '@.refresh_token' > "$SV_VAR/refresh_token" 2>/dev/null || true
			printf '%s' "$email" > "$SV_VAR/email"
			echo "$out"
			return 0
			;;
	esac
	rm -f "$SV_VAR/access_token" "$SV_VAR/refresh_token"
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
