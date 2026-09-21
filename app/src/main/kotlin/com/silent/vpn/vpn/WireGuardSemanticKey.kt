package com.silent.vpn.vpn

/** Configuration identity used to skip redundant WireGuard reconfiguration. Never log this key. */
internal object WireGuardSemanticKey {
    fun from(config: String): String {
        fun field(name: String, unordered: Boolean = false): String {
            val value = Regex("""(?m)^\s*$name\s*=\s*([^\r\n]*)""")
                .find(config)?.groupValues?.getOrNull(1)?.trim().orEmpty()
            return if (unordered) {
                value.split(',')
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                    .distinct()
                    .sorted()
                    .joinToString(",")
            } else {
                value
            }
        }
        return listOf(
            field("PrivateKey"),
            field("Address", unordered = true),
            field("PublicKey"),
            field("PresharedKey"),
            field("Endpoint"),
            field("AllowedIPs", unordered = true),
            field("DNS"),
            field("PersistentKeepalive"),
        ).joinToString("|")
    }
}
