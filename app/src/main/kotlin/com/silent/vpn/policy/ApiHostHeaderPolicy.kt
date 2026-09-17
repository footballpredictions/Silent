package com.silent.vpn.policy

/**
 * Host: nip.io нужен только публичному HTTPS по IP (nginx vhost).
 * На 10.66.66.1:8000 Host nip.io → HTTP :80 Улья отвечает 301 → OkHttp
 * меняет POST register на GET → «API endpoint not found».
 */
object ApiHostHeaderPolicy {

    fun shouldSetNipIoHost(
        host: String,
        tunnelGateway: String = VpnNetworkConstants.WG_TUNNEL_GATEWAY,
    ): Boolean {
        val h = host.trim()
        if (!h.matches(IPV4)) return false
        if (h == tunnelGateway) return false
        if (h.startsWith("127.")) return false
        return true
    }

    fun nipIoHostHeader(
        host: String,
        nipHost: String = VpnNetworkConstants.DEFAULT_SERVER_HOST,
        tunnelGateway: String = VpnNetworkConstants.WG_TUNNEL_GATEWAY,
    ): String? =
        if (shouldSetNipIoHost(host, tunnelGateway)) nipHost else null

    private val IPV4 = Regex("""\d+\.\d+\.\d+\.\d+""")
}
