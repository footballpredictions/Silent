# Shared server policy, with last-good persistent cache and packaged fallback.
. "$SV_LIB/common.sh"
. "$SV_LIB/catalog-dns.sh"

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
	local file="$1" rev dir profile
	[ "$(wc -c < "$file")" -le 262144 ] || return 1
	[ "$(jsonfilter -i "$file" -e '@.schema_version' 2>/dev/null)" = 1 ] || return 1
	rev="$(jsonfilter -i "$file" -e '@.revision' 2>/dev/null)"
	[ "${#rev}" = 64 ] || return 1
	case "$rev" in *[!0-9a-f]*) return 1 ;; esac
	profile="$(jsonfilter -i "$file" -e '@.profile' 2>/dev/null)"
	case "$profile" in ''|catalog-test) ;; *) return 1 ;; esac
	if [ "$profile" = catalog-test ]; then
		[ -x "$SV_LIB/silent-dns" ] || return 1
	fi
	# jsonfilter must see arrays (an empty list is a valid administrator choice).
	jsonfilter -i "$file" -e '@.direct_domains' 2>/dev/null | grep -q '^\[' || return 1
	jsonfilter -i "$file" -e '@.vpn_domains' 2>/dev/null | grep -q '^\[' || return 1
	dir="$(mktemp -d "$SV_RUN/policy-check.XXXXXX")" || return 1
	jsonfilter -i "$file" -e '@.direct_domains[*]' > "$dir/direct" 2>/dev/null
	jsonfilter -i "$file" -e '@.vpn_domains[*]' > "$dir/vpn" 2>/dev/null
	if jsonfilter -i "$file" -e '@.direct_exact_domains' > "$dir/exact.raw" 2>/dev/null; then
		grep -q '^\[' "$dir/exact.raw" || { rm -rf "$dir"; return 1; }
	fi
	jsonfilter -i "$file" -e '@.direct_exact_domains[*]' > "$dir/exact" 2>/dev/null || true
	if sv_policy_domains_valid "$dir/direct" && sv_policy_domains_valid "$dir/vpn" && sv_policy_domains_valid "$dir/exact"; then
		rm -rf "$dir"
		return 0
	fi
	rm -rf "$dir"
	return 1
}

sv_policy_remember_applied() {
	local applied snapshot revision
	applied="$(cat "$SV_RUN/policy.applied" 2>/dev/null)"
	[ -n "$applied" ] && [ -s "$SV_VAR/routing-policy.json" ] || return 0
	if [ -s "$SV_RUN/policy.applied.json" ] &&
	   [ "$(jsonfilter -i "$SV_RUN/policy.applied.json" -e '@.revision' 2>/dev/null)" = "$applied" ]; then return 0; fi
	snapshot="$(mktemp "$SV_RUN/policy-applied.XXXXXX")" || return 1
	if ! cp "$SV_VAR/routing-policy.json" "$snapshot"; then rm -f "$snapshot"; return 1; fi
	revision="$(jsonfilter -i "$snapshot" -e '@.revision' 2>/dev/null)"
	# A concurrent fetch must not label a newer policy as already applied.
	if [ "$revision" != "$applied" ] || [ "$(cat "$SV_RUN/policy.applied" 2>/dev/null)" != "$applied" ]; then
		rm -f "$snapshot"
		return 0
	fi
	mv "$snapshot" "$SV_RUN/policy.applied.json"
}

sv_policy_preserves_applied() {
	local applied
	[ -s "$SV_RUN/policy.applied.json" ] && [ -x "$SV_LIB/silent-dns" ] || return 1
	applied="$(cat "$SV_RUN/policy.applied" 2>/dev/null)"
	[ -n "$applied" ] &&
		[ "$(jsonfilter -i "$SV_RUN/policy.applied.json" -e '@.revision' 2>/dev/null)" = "$applied" ] || return 1
	[ -z "${1:-}" ] || [ "$(jsonfilter -i "$SV_VAR/routing-policy.json" -e '@.revision' 2>/dev/null)" = "$1" ] || return 1
	# The common Go parser checks suffix/exact coverage and forced-VPN priority.
	# Missing/older helpers fail closed to the existing invalidation behavior.
	GOMEMLIMIT=8MiB GOGC=50 "$SV_LIB/silent-dns" -policy "$SV_VAR/routing-policy.json" \
		-preserves-policy "$SV_RUN/policy.applied.json" >/dev/null 2>&1 || return 1
	[ -z "${1:-}" ] || [ "$(jsonfilter -i "$SV_VAR/routing-policy.json" -e '@.revision' 2>/dev/null)" = "$1" ]
}

sv_policy_fetch() {
	local base tmp saved query queries
	sv_mkdir
	tmp="$(mktemp "$SV_RUN/policy-download.XXXXXX")" || return 1
	for base in $(sv_policy_bases); do
		queries='standard'
		if sv_catalog_dns_selected; then queries='catalog standard'; fi
		for query in $queries; do
			case "$query" in catalog) query='?profile=catalog-test' ;; *) query='' ;; esac
		: > "$tmp"
		# Policy has no credentials; error JSON/HTML must not stop cell fallback.
		if wget -q -O "$tmp" --timeout="$(sv_hive_timeout_for "$base")" \
			"$base/api/vpn/routing-policy$query" 2>/dev/null && sv_policy_validate "$tmp"; then
			if ! cmp -s "$tmp" "$SV_VAR/routing-policy.json"; then
				# Background refresh and first-time connect can finish together.
				# Each validated writer needs its own file until the atomic rename.
				saved="$(mktemp "$SV_VAR/routing-policy.XXXXXX")" || { rm -f "$tmp"; return 1; }
				if ! { cp "$tmp" "$saved" && chmod 600 "$saved" && mv "$saved" "$SV_VAR/routing-policy.json"; }; then
					rm -f "$tmp" "$saved"
					return 1
				fi
				rm -f "$tmp"
			else
				rm -f "$tmp"
			fi
			return 0
		fi
		done
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
	jsonfilter -i "$file" -e '@.direct_exact_domains[*]' > "$dir/direct-exact.domains.new" 2>/dev/null || true
	mv "$dir/direct.domains.new" "$dir/direct.domains"
	mv "$dir/vpn.domains.new" "$dir/vpn.domains"
	mv "$dir/direct-exact.domains.new" "$dir/direct-exact.domains"
	SV_RU_LIST="$dir/direct.domains"
	SV_RU_VPN_LIST="$dir/vpn.domains"
}
