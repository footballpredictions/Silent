package com.silent.vpn.service

import android.content.Intent
import android.net.IpPrefix
import android.os.Build
import android.os.ParcelFileDescriptor
import com.silent.vpn.util.DebugLog
import com.wireguard.android.backend.GoBackend
import java.net.InetAddress

/**
 * GoBackend VpnService + excludeRoute для site-bypass (API 33+).
 * AllowedIPs complement не всегда пробивает дыры на OEM; excludeRoute — как в hev/olcrtc.
 */
class SilentGoBackendVpnService : GoBackend.VpnService() {

    companion object {
        /** Дыры 0.0.0.0/0 (IP/CIDR) — задаёт WireGuardHelper перед establish(). */
        @Volatile var vpnExcludeRouteCidrs: List<String> = emptyList()
    }

    override fun getBuilder(): Builder = SiteBypassVpnBuilder()

    override fun onRevoke() {
        DebugLog.w("GoBackendVpn", "VPN revoked by system (another VPN connected)")
        vpnExcludeRouteCidrs = emptyList()
        super.onRevoke()
        startService(
            Intent(this, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_EXTERNAL_REVOKED
            },
        )
    }

    private inner class SiteBypassVpnBuilder : Builder() {
        override fun establish(): ParcelFileDescriptor? {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val n = applyExcludeRoutes(this, vpnExcludeRouteCidrs)
                if (n > 0) {
                    DebugLog.i("GoBackendVpn", "excludeRoute site-bypass: $n cidr(s)")
                }
            }
            return super.establish()
        }
    }

    private fun applyExcludeRoutes(builder: Builder, cidrs: List<String>): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return 0
        var n = 0
        for (cidr in cidrs) {
            val parts = cidr.trim().split("/")
            if (parts.size != 2) continue
            val ip = parts[0]
            val prefix = parts[1].toIntOrNull() ?: continue
            if (!IPV4.matches(ip) || prefix !in 0..32) continue
            val addr = runCatching { InetAddress.getByName(ip) }.getOrNull() ?: continue
            if (addr.address?.size != 4) continue
            runCatching {
                builder.excludeRoute(IpPrefix(addr, prefix))
                n++
            }
        }
        return n
    }

    private val IPV4 = Regex("""^\d{1,3}(\.\d{1,3}){3}$""")
}
