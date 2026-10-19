package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import java.net.Inet4Address

/**
 * Local LAN stays outside the Android VpnService tunnel (like Windows on-link /24),
 * so the OpenWrt panel at 192.168.x.1 remains reachable while Silent VPN is up.
 *
 * Never exclude 10.66.0.0/16 — that is the WireGuard API overlay.
 */
object LanBypassRoutes {
    /** Broad home ranges; 10/8 omitted so 10.66.66.1 stays in-tunnel. */
    fun defaultHomeLanCidrs(): List<String> = listOf(
        "192.168.0.0/16",
        "172.16.0.0/12",
    )

    /** Site-bypass holes stay as-is; LAN list is filtered (no WG overlay / public IPs). */
    fun mergeExcludeCidrs(
        siteHoles: Collection<String> = emptyList(),
        lanCidrs: Collection<String> = emptyList(),
    ): List<String> {
        val merged = LinkedHashSet<String>()
        for (raw in siteHoles) {
            normalizeHoleCidr(raw)?.let { merged.add(it) }
        }
        for (raw in lanCidrs) {
            normalizeLanCidr(raw)?.let { merged.add(it) }
        }
        return merged.sorted()
    }

    fun sanitizeLanCidrs(cidrs: Collection<String>): List<String> =
        cidrs.mapNotNull(::normalizeLanCidr).distinct().sorted()

    /** Underlay Wi‑Fi / Ethernet prefixes (not the VPN network). */
    fun underlayLanCidrs(context: Context): List<String> {
        val out = LinkedHashSet<String>()
        forEachUnderlayLan(context) { props ->
            for (link in props.linkAddresses) {
                val addr = link.address as? Inet4Address ?: continue
                val host = addr.hostAddress ?: continue
                val prefix = link.prefixLength
                if (prefix !in 1..32) continue
                normalizeLanCidr("$host/$prefix")?.let { out.add(it) }
            }
            // Public DHCP getter was added in API 30. Calling it on Android 10
            // raises NoSuchMethodError (not Exception) and terminates VPN startup.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                props.dhcpServerAddress?.hostAddress?.let { dhcp ->
                    normalizeLanCidr("$dhcp/32")?.let { out.add(it) }
                }
            }
            props.routes.orEmpty().forEach { route ->
                val gw = route.gateway as? Inet4Address ?: return@forEach
                val g = gw.hostAddress ?: return@forEach
                normalizeLanCidr("$g/32")?.let { out.add(it) }
            }
        }
        return out.toList()
    }

    private fun forEachUnderlayLan(
        context: Context,
        block: (android.net.LinkProperties) -> Unit,
    ) {
        val cm = context.getSystemService(ConnectivityManager::class.java) ?: return
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
            val eth = caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
            if (!wifi && !eth) continue
            val props = cm.getLinkProperties(network) ?: continue
            block(props)
        }
    }

    fun normalizeHoleCidr(raw: String): String? {
        val s = raw.trim()
        if (s.isEmpty()) return null
        val parts = s.split("/")
        val ip = parts[0]
        val prefix = parts.getOrNull(1)?.toIntOrNull() ?: 32
        if (!IPV4.matches(ip) || prefix !in 0..32) return null
        return "$ip/$prefix"
    }

    fun normalizeLanCidr(raw: String): String? {
        val hole = normalizeHoleCidr(raw) ?: return null
        val ip = hole.substringBefore('/')
        val octets = ip.split('.').map { it.toInt() }
        if (octets.any { it !in 0..255 }) return null
        val prefix = hole.substringAfter('/').toInt()
        val privatePrefix = when {
            octets[0] == 10 -> 8
            octets[0] == 172 && octets[1] in 16..31 -> 12
            octets[0] == 192 && octets[1] == 168 -> 16
            else -> return null
        }
        if (prefix < privatePrefix) return null
        // LinkProperties supplies host/prefix, e.g. 10.1.2.3/8. Compare the
        // whole prefix with 10.66/16, not just the host or literal 10.0.0.0/8.
        val address = octets.fold(0L) { value, octet -> (value shl 8) or octet.toLong() }
        val mask = (0xffffffffL shl (32 - minOf(prefix, 16))) and 0xffffffffL
        if (address and mask == 0x0a420000L and mask) return null
        return hole
    }

    private val IPV4 = Regex("""^\d{1,3}(\.\d{1,3}){3}$""")
}
