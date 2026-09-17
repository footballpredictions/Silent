package com.silent.vpn.policy

/**
 * WireGuard у нас IPv4-only. Добавлять IPv6-адрес/маршрут на GoBackend Builder
 * нельзя: wg-go после establish делает set address только по IPv4 из конфига
 * и падает с «Unable to set IP address» — туннель не поднимается.
 *
 * `::/0` в сам WG-конфиг тоже нельзя (KeyFormatException, 2026-08-16).
 */
object Ipv6LeakPolicy {

    fun shouldCaptureIpv6OnGoBackendBuilder(): Boolean = false

    fun isWireGuardAllowedIpsSafe(allowedIps: String): Boolean {
        val parts = allowedIps.split(',').map { it.trim().lowercase() }.filter { it.isNotEmpty() }
        return parts.none { it == "::/0" || it.startsWith("::/") }
    }

    /**
     * Gmail/Chrome на IPv6 уходят мимо WG (`0.0.0.0/0` не ловит ::).
     * На LTE с ТСПУ это «письмо не приходит». ::/0 в WG-конфиг нельзя —
     * режем underlay через VpnService.setBlocking на полном bootstrap.
     * Overlay-brief (узкий AllowedIPs) не блокируем: иначе почта останется
     * только с 10.66.66.0/24.
     */
    fun shouldBlockUnderlyingNetwork(
        isBootstrap: Boolean,
        apiOverlayMode: Boolean,
        includeAppOverlay: Boolean,
    ): Boolean = isBootstrap && !apiOverlayMode && !includeAppOverlay
}
