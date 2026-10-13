# Shared server policy, with last-good persistent cache and packaged fallback.
. "$SV_LIB/common.sh"

sv_policy_bases() {
	[ -f "$SV_RUN/path.up" ] && echo "$SV_TUNNEL_API"
	echo "$SV_PUBLIC_API"
	# Public failover proxies on cells forward /api/vpn/* to the hive.
	echo http://87.58.213.193:9100
	echo http://78.17.74.27:9100
	echo http://192.177.26.38:9100
	echo http://89.37.192.241:9100
}

sv_policy_domains_valid() {
	awk '
	length($0) > 253 || /[^a-z0-9.-]/ || /^\./ || /\.$/ || /\.\./ { exit 1 }
	{ n=split($0,a,"."); for(i=1;i<=n;i++) if(length(a[i])>63 || a[i]=="" || a[i] ~ /^-/ || a[i] ~ /-$/) exit 1 }
	END { if(NR>2000) exit 1 }
	' "$1"
}

sv_policy_validate() {
	local file="$1" rev dir
	[ "$(wc -c < "$file")" -le 262144 ] || return 1
	[ "$(jsonfilter -i "$file" -e '@.schema_version' 2>/dev/null)" = 1 ] || return 1
	rev="$(jsonfilter -i "$file" -e '@.revision' 2>/dev/null)"
	[ "${#rev}" = 64 ] || return 1
	case "$rev" in *[!0-9a-f]*) return 1 ;; esac
	# jsonfilter must see arrays (an empty list is a valid administrator choice).
	jsonfilter -i "$file" -e '@.direct_domains' 2>/dev/null | grep -q '^\[' || return 1
	jsonfilter -i "$file" -e '@.vpn_domains' 2>/dev/null | grep -q '^\[' || return 1
	dir="$(mktemp -d "$SV_RUN/policy-check.XXXXXX")" || return 1
	jsonfilter -i "$file" -e '@.direct_domains[*]' > "$dir/direct" 2>/dev/null
	jsonfilter -i "$file" -e '@.vpn_domains[*]' > "$dir/vpn" 2>/dev/null
	if sv_policy_domains_valid "$dir/direct" && sv_policy_domains_valid "$dir/vpn"; then
		rm -rf "$dir"
		return 0
	fi
	rm -rf "$dir"
	return 1
}

sv_policy_fetch() {
	local base tmp
	sv_mkdir
	tmp="$(mktemp "$SV_RUN/policy-download.XXXXXX")" || return 1
	for base in $(sv_policy_bases); do
		: > "$tmp"
		# Policy has no credentials; error JSON/HTML must not stop cell fallback.
		if wget -q -O "$tmp" --timeout="$(sv_hive_timeout_for "$base")" \
			"$base/api/vpn/routing-policy" 2>/dev/null && sv_policy_validate "$tmp"; then
			if ! cmp -s "$tmp" "$SV_VAR/routing-policy.json"; then
				cp "$tmp" "$SV_VAR/routing-policy.json.new" || { rm -f "$tmp"; return 1; }
				chmod 600 "$SV_VAR/routing-policy.json.new"
				mv "$SV_VAR/routing-policy.json.new" "$SV_VAR/routing-policy.json"
				rm -f "$tmp"
			else
				rm -f "$tmp"
			fi
			return 0
		fi
	done
	rm -f "$tmp"
	return 1
}

sv_policy_use_cache() {
	local file="$SV_VAR/routing-policy.json" dir
	[ -s "$file" ] && sv_policy_validate "$file" || return 0
	dir="$SV_RUN/routing-policy"
	mkdir -p "$dir" || return 1
	jsonfilter -i "$file" -e '@.direct_domains[*]' > "$dir/direct.domains.new" 2>/dev/null || true
	jsonfilter -i "$file" -e '@.vpn_domains[*]' > "$dir/vpn.domains.new" 2>/dev/null || true
	mv "$dir/direct.domains.new" "$dir/direct.domains"
	mv "$dir/vpn.domains.new" "$dir/vpn.domains"
	SV_RU_LIST="$dir/direct.domains"
	SV_RU_VPN_LIST="$dir/vpn.domains"
}
