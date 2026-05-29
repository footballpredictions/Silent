package com.silent.vpn.vpn

/** Split-tunnel AllowedIPs: 0.0.0.0/0 minus TURN/server hosts (как PC/reference). */
object AllowedIpsHelper {
    fun generateExclusionAllowedIPs(excludeIPs: Collection<String>): String {
        val unique = excludeIPs.map { it.trim() }.filter { it.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) }.distinct()
        if (unique.isEmpty()) return "0.0.0.0/0"

        var networks = listOf(0L to 0)
        for (ip in unique) {
            val excl = ipToNum(ip)
            networks = networks.flatMap { (net, pfx) -> cidrExclude(net, pfx, excl) }
        }
        return networks.joinToString(", ") { (n, p) -> "${numToIp(n)}/$p" }
    }

    fun patchAllowedIPs(config: String, excludeIPs: Collection<String>): String {
        if (excludeIPs.isEmpty()) return config
        val allowed = generateExclusionAllowedIPs(excludeIPs)
        return config.replace(Regex("(?m)^AllowedIPs\\s*=\\s*.+$"), "AllowedIPs = $allowed")
    }

    private fun ipToNum(ip: String): Long =
        ip.split('.').fold(0L) { acc, oct -> ((acc shl 8) or (oct.toLong() and 0xFF)) and 0xFFFFFFFFL }

    private fun numToIp(n: Long): String =
        listOf((n shr 24) and 0xFF, (n shr 16) and 0xFF, (n shr 8) and 0xFF, n and 0xFF).joinToString(".")

    private fun cidrExclude(netNum: Long, prefix: Int, excludeNum: Long): List<Pair<Long, Int>> {
        val mask = if (prefix == 0) 0L else ((0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL)
        if ((excludeNum and mask) != (netNum and mask)) return listOf(netNum to prefix)
        if (prefix == 32) return emptyList()
        val np = prefix + 1
        val nm = ((0xFFFFFFFFL shl (32 - np)) and 0xFFFFFFFFL)
        val left = netNum
        val right = (netNum or (1L shl (31 - prefix))) and 0xFFFFFFFFL
        return if ((excludeNum and nm) == (left and nm)) {
            cidrExclude(left, np, excludeNum) + listOf(right to np)
        } else {
            listOf(left to np) + cidrExclude(right, np, excludeNum)
        }
    }
}
