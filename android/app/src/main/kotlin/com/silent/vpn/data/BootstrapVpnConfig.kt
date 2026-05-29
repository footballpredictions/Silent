package com.silent.vpn.data

import java.net.URI

/** Локальный bootstrap-конфиг без HTTPS к бекенду (нужен на мобильном интернете с белыми списками). */
object BootstrapVpnConfig {
    private const val SERVER_HOST = "132.243.234.162"
    const val SERVER_PORT = 56000
    /** WDTT master password на сервере — для pre-login bootstrap-сессии. */
    private const val WDTT_MASTER_PASSWORD = "hAKfvX0lUTNuXJueD9Zx"

    fun serverHost(): String {
        return runCatching {
            val host = URI(SilentRepository.DEFAULT_SERVER_URL).host
            if (!host.isNullOrBlank()) host else SERVER_HOST
        }.getOrDefault(SERVER_HOST)
    }

    fun build(vkHash: String, preLoginFingerprint: String): VpnConfig {
        val fp = preLoginFingerprint.trim()
        return VpnConfig(
            device_id = "boot:$fp",
            wg_private_key = "",
            wg_address = "",
            wg_dns = "77.88.8.8,77.88.8.1",
            server_ip = serverHost(),
            server_port = SERVER_PORT,
            server_public_key = "",
            wdtt_password = WDTT_MASTER_PASSWORD,
            vk_hashes = listOf(vkHash),
            stream_count = 3,
        )
    }
}
