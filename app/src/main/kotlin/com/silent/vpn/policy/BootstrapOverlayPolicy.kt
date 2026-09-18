package com.silent.vpn.policy

/** Временный VPN на экране входа: UDP Улья флапает — overlay на живую соту. */
data class BootstrapOverlayEndpoint(
    val ip: String,
    val port: Int,
    val isHive: Boolean,
)

object BootstrapOverlayPolicy {
    const val DEFAULT_WDTT_PORT = 56000
    val AI_EXIT_IPS: Set<String> = setOf("192.177.26.38")

    fun cellIpsFromUrls(
        urls: List<String>,
        hiveIps: Set<String> = setOf("89.125.188.100", "89-125-188-100.nip.io"),
        skipIps: Set<String> = AI_EXIT_IPS,
    ): List<String> {
        val hive = hiveIps.map { it.trim().lowercase() }.filter { it.isNotBlank() }.toSet()
        val skip = skipIps.map { it.trim().lowercase() }.toSet()
        val out = LinkedHashSet<String>()
        for (raw in urls) {
            val host = hostOf(raw) ?: continue
            val key = host.lowercase()
            if (key in hive || key in skip) continue
            if (host.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) out.add(host)
        }
        return out.toList()
    }

    fun pick(
        hiveIp: String,
        hivePort: Int = DEFAULT_WDTT_PORT,
        cellIps: List<String>,
        cellPort: Int = DEFAULT_WDTT_PORT,
    ): BootstrapOverlayEndpoint {
        val hive = hiveIp.trim()
        val cell = cellIps.map { it.trim() }.firstOrNull { it.isNotBlank() && it != hive }
        if (cell != null) {
            return BootstrapOverlayEndpoint(cell, cellPort, isHive = false)
        }
        return BootstrapOverlayEndpoint(hive, hivePort, isHive = true)
    }

    private fun hostOf(raw: String): String? {
        val s = raw.trim()
        if (s.isEmpty()) return null
        val withScheme = if ("://" in s) s else "http://$s"
        return runCatching { java.net.URI(withScheme).host }.getOrNull()?.trim()?.trimEnd('.')
    }
}
