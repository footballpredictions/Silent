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
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
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

    /** Router DNS from underlay — so `{lan}.silent.vpn` resolves while VPN is up. */
    fun underlayLanDnsServers(context: Context): List<String> {
        val out = LinkedHashSet<String>()
        forEachUnderlayLan(context) { props ->
            for (server in props.dnsServers) {
                val ip = (server as? Inet4Address)?.hostAddress ?: continue
                if (normalizeLanCidr("$ip/32") != null) out.add(ip)
            }
            props.routes.orEmpty().forEach { route ->
                val dest = route.destination
                val isDefault = dest == null || dest.prefixLength == 0
                if (!isDefault) return@forEach
                val gw = (route.gateway as? Inet4Address)?.hostAddress ?: return@forEach
                if (normalizeLanCidr("$gw/32") != null) out.add(gw)
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
        if (!isPrivateLan(ip)) return null
        if (isWgOverlay(ip)) return null
        // Never punch the whole 10/8 — would steal 10.66.66.1 from the tunnel.
        if (ip == "10.0.0.0" && hole.endsWith("/8")) return null
        return hole
    }

    private fun isPrivateLan(ip: String): Boolean {
        val o = ip.split(".").mapNotNull { it.toIntOrNull() }
        if (o.size != 4) return false
        val a = o[0]
        val b = o[1]
        return when {
            a == 10 -> true
            a == 172 && b in 16..31 -> true
            a == 192 && b == 168 -> true
            else -> false
        }
    }

    /** Silent WG client/API plane — must stay inside the tunnel. */
    private fun isWgOverlay(ip: String): Boolean {
        val o = ip.split(".").mapNotNull { it.toIntOrNull() }
        if (o.size != 4) return false
        return o[0] == 10 && o[1] == 66
    }

    private val IPV4 = Regex("""^\d{1,3}(\.\d{1,3}){3}$""")
}
