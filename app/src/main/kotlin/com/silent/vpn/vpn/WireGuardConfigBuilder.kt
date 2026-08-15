package com.silent.vpn.vpn

import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.VpnConfig

object WireGuardConfigBuilder {
    fun isValidWgKey(raw: String): Boolean {
        val s = raw.trim()
        if (s.length !in 43..44) return false
        return runCatching {
            val decoded = android.util.Base64.decode(s, android.util.Base64.DEFAULT)
            decoded.size == 32
        }.getOrDefault(false)
    }

    /** Собрать wg-конфиг из ответа API (не ждать box-drawing в логах libclient). */
    fun fromVpnConfig(cfg: VpnConfig, listenPort: Int = 9000, dnsOverride: String? = null): String? {
        val priv = cfg.wg_private_key.trim()
        val pub = cfg.server_public_key.trim()
        val addr = cfg.wg_address.trim()
        if (!isValidWgKey(priv) || !isValidWgKey(pub) || addr.isBlank()) return null
        val dns = dnsOverride?.takeIf { it.isNotBlank() }
            ?: cfg.wg_dns.ifBlank { DnsPreset.FALLBACK.servers }
        return buildString {
            appendLine("[Interface]")
            appendLine("PrivateKey = $priv")
            appendLine("Address = $addr")
            appendLine("MTU = 1200")
            appendLine("DNS = $dns")
            appendLine()
            appendLine("[Peer]")
            appendLine("PublicKey = $pub")
            appendLine("Endpoint = 127.0.0.1:$listenPort")
            appendLine("AllowedIPs = 0.0.0.0/0")
            appendLine("PersistentKeepalive = 25")
        }
    }
}
