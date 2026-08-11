package com.silent.vpn.vpn

/** Split-tunnel AllowedIPs: WG subnet only или 0.0.0.0/0 minus hosts/CIDRs. */
object AllowedIpsHelper {
    const val WG_TUNNEL_SUBNET = "10.66.66.0/24"

    /** Только подсеть WG в туннеле — API (10.66.66.1) через VPN, TURN/VK напрямую. */
    fun patchAllowedIPsToSubnet(config: String, subnet: String = WG_TUNNEL_SUBNET): String =
        config.replace(Regex("(?m)^AllowedIPs\\s*=\\s*.+$"), "AllowedIPs = $subnet")

    /**
     * Bootstrap: API в WG + HTTPS бекенда (verify/reset из браузера/почты).
     * TURN/VK — вне AllowedIPs, идут напрямую по мобильной сети.
     */
    fun patchAllowedIPsForBootstrapAuth(config: String, serverIp: String): String {
        val ip = serverIp.trim()
        val allowed = if (ip.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) {
            "$WG_TUNNEL_SUBNET, $ip/32"
        } else {
            WG_TUNNEL_SUBNET
        }
        return config.replace(Regex("(?m)^AllowedIPs\\s*=\\s*.+$"), "AllowedIPs = $allowed")
    }

    /**
     * Компактный комплемент 0.0.0.0/0 минус IP (/32) и CIDR-дыры.
     * Принимает `1.2.3.4`, `1.2.3.4/32`, `10.0.0.0/8`.
     */
    fun generateExclusionAllowedIPs(excludeIPs: Collection<String>): String {
        val holes = linkedSetOf<Ipv4Cidr>()
        for (raw in excludeIPs) {
            val s = raw.trim()
            if (s.isEmpty()) continue
            parseHole(s)?.let { holes.add(it) }
        }
        if (holes.isEmpty()) return "0.0.0.0/0"
        val allowed = SiteBypassRoutes.complementCidrs(holes)
        if (allowed.isEmpty()) return "0.0.0.0/0"
        return allowed.joinToString(", ") { it.toString() }
    }

    fun patchAllowedIPs(config: String, excludeIPs: Collection<String>): String {
        if (excludeIPs.isEmpty()) return config
        val allowed = generateExclusionAllowedIPs(excludeIPs)
        return config.replace(Regex("(?m)^AllowedIPs\\s*=\\s*.+$"), "AllowedIPs = $allowed")
    }

    /** Main VPN mobile: явно 10.66.66.0/24 для API (без overlay toggle). */
    fun patchAllowedIPsEnsureApiSubnet(config: String, subnet: String = WG_TUNNEL_SUBNET): String {
        val regex = Regex("(?m)^AllowedIPs\\s*=\\s*(.+)$")
        val match = regex.find(config) ?: return config.replace(
            Regex("(?m)^\\[Peer\\]"),
            "AllowedIPs = $subnet\n\n[Peer]",
        )
        val existing = match.groupValues[1].trim()
        if (existing.contains(subnet)) return config
        return config.replace(regex, "AllowedIPs = $existing, $subnet")
    }

    private fun parseHole(s: String): Ipv4Cidr? {
        val slash = s.indexOf('/')
        if (slash < 0) {
            if (!s.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) return null
            val ip = ipToNum(s)
            return Ipv4Cidr(ip, 32)
        }
        val host = s.substring(0, slash)
        val prefix = s.substring(slash + 1).toIntOrNull() ?: return null
        if (!host.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) || prefix !in 0..32) return null
        return Ipv4Cidr(ipToNum(host), prefix).networkCidr()
    }

    private fun ipToNum(ip: String): Long =
        ip.split('.').fold(0L) { acc, oct -> ((acc shl 8) or (oct.toLong() and 0xFF)) and 0xFFFFFFFFL }
}
