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
}
