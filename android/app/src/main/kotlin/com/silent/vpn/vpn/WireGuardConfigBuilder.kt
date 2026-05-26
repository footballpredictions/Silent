package com.silent.vpn.vpn

import com.silent.vpn.data.VpnConfig

object WireGuardConfigBuilder {
    /** Собрать wg-конфиг из ответа API (не ждать box-drawing в логах libclient). */
    fun fromVpnConfig(cfg: VpnConfig, listenPort: Int = 9000): String? {
        val priv = cfg.wg_private_key.trim()
        val pub = cfg.server_public_key.trim()
        if (priv.isBlank() || pub.isBlank()) return null
        val dns = cfg.wg_dns.ifBlank { "77.88.8.8,77.88.8.1" }
        return buildString {
            appendLine("[Interface]")
            appendLine("PrivateKey = $priv")
            appendLine("Address = ${cfg.wg_address}")
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
