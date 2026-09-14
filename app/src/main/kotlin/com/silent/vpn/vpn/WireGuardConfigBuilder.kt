package com.silent.vpn.vpn

import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.VpnConfig

object WireGuardConfigBuilder {
    /** Обычные слоты (Telegram / общая стабильность). */
    const val MTU_DEFAULT = 1200
    /** Только Сервер 3 (Сота 2) — Steam SDR ~1300-byte UDP. */
    const val MTU_GAME = 1420
    const val GAME_SERVER_SLOT = "server3"
    const val GAME_SERVER_IP = "78.17.74.27"

    fun isValidWgKey(raw: String): Boolean {
        val s = raw.trim()
        if (s.length !in 43..44) return false
        return runCatching {
            val decoded = android.util.Base64.decode(s, android.util.Base64.DEFAULT)
            decoded.size == 32
        }.getOrDefault(false)
    }

    fun mtuForConfig(cfg: VpnConfig): Int {
        val slot = cfg.selected_server?.trim()?.lowercase().orEmpty()
        val ip = cfg.server_ip.trim()
        return mtuForSlotAndIp(slot, ip)
    }

    fun mtuForSlotAndIp(slotRaw: String?, serverIp: String?): Int {
        val slot = SilentRepository.normalizePreferredServer(slotRaw)
        val ip = serverIp?.trim().orEmpty()
        if (slot == GAME_SERVER_SLOT || ip == GAME_SERVER_IP) return MTU_GAME
        if (SilentRepository.BAKED_SERVER_IPS[slot] == GAME_SERVER_IP) return MTU_GAME
        return MTU_DEFAULT
    }

    /** Preferred slot из prefs — источник истины при apply (GETCONF часто шлёт MTU 1280). */
    fun mtuForPreferredSlot(context: android.content.Context): Int {
        val prefs = SilentPrefs.open(context)
        val slot = prefs.getString(SilentRepository.PREF_PREFERRED_SERVER, null)
        val bakedIp = SilentRepository.BAKED_SERVER_IPS[SilentRepository.normalizePreferredServer(slot)]
        return mtuForSlotAndIp(slot, bakedIp)
    }

    /** Собрать wg-конфиг из ответа API (не ждать box-drawing в логах libclient). */
    fun fromVpnConfig(cfg: VpnConfig, listenPort: Int = 9000, dnsOverride: String? = null): String? {
        val priv = cfg.wg_private_key.trim()
        val pub = cfg.server_public_key.trim()
        val addr = cfg.wg_address.trim()
        if (!isValidWgKey(priv) || !isValidWgKey(pub) || addr.isBlank()) return null
        val dns = dnsOverride?.takeIf { it.isNotBlank() }
            ?: cfg.wg_dns.ifBlank { DnsPreset.FALLBACK.servers }
        val mtu = mtuForConfig(cfg)
        return buildString {
            appendLine("[Interface]")
            appendLine("PrivateKey = $priv")
            appendLine("Address = $addr")
            appendLine("MTU = $mtu")
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
