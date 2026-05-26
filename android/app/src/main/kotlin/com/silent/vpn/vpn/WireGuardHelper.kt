package com.silent.vpn.vpn

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log
import com.silent.vpn.SilentApp
import com.wireguard.android.backend.GoBackend
import com.wireguard.android.backend.Tunnel
import com.wireguard.config.Config
import com.wireguard.config.Interface
import com.wireguard.config.Peer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream

class WireGuardHelper(context: Context) {
    private val appContext = context.applicationContext
    private val backend = (appContext as SilentApp).getBackend(context)

    private companion object {
        val wgMutex = Mutex()
        var sharedTunnel: WgTunnel? = null
        private const val TAG = "WireGuardHelper"

        /** Split-tunnel: 0.0.0.0/0 minus TURN/VPS IPs so DTLS is not blocked by WFP. */
        fun generateExclusionAllowedIPs(excludeIPs: Collection<String>): String {
            if (excludeIPs.isEmpty()) return "0.0.0.0/0"

            fun ipToNum(ip: String): Long {
                val p = ip.split(".")
                return ((p[0].toLong() shl 24) or (p[1].toLong() shl 16) or
                    (p[2].toLong() shl 8) or p[3].toLong()) and 0xFFFFFFFFL
            }

            fun numToIp(n: Long): String {
                val x = n and 0xFFFFFFFFL
                return "${(x ushr 24) and 0xFF}.${(x ushr 16) and 0xFF}.${(x ushr 8) and 0xFF}.${x and 0xFF}"
            }

            fun cidrExclude(netNum: Long, prefix: Int, excludeNum: Long): List<Pair<Long, Int>> {
                val mask = if (prefix == 0) 0L else (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
                if ((excludeNum and mask) != (netNum and mask)) return listOf(netNum to prefix)
                if (prefix == 32) return emptyList()
                val np = prefix + 1
                val nm = (0xFFFFFFFFL shl (32 - np)) and 0xFFFFFFFFL
                val left = netNum
                val right = (netNum or (1L shl (31 - prefix))) and 0xFFFFFFFFL
                return if ((excludeNum and nm) == (left and nm)) {
                    cidrExclude(left, np, excludeNum) + listOf(right to np)
                } else {
                    listOf(left to np) + cidrExclude(right, np, excludeNum)
                }
            }

            var networks = listOf(0L to 0)
            for (ip in excludeIPs.map { it.trim() }.filter { it.isNotBlank() }) {
                val excl = ipToNum(ip)
                networks = networks.flatMap { (net, pfx) -> cidrExclude(net, pfx, excl) }
            }
            return networks.joinToString(", ") { (n, p) -> "${numToIp(n)}/$p" }
        }
    }

    class WgTunnel : Tunnel {
        override fun getName() = "silent"
        override fun onStateChange(newState: Tunnel.State) {}
    }

    suspend fun startTunnel(configString: String, excludeIPs: Collection<String> = emptyList()) = wgMutex.withLock {
        withContext(Dispatchers.IO) {
            if (VpnService.prepare(appContext) != null) {
                throw IllegalStateException("VPN-разрешение не выдано")
            }
            ensureGoBackendServiceStarted()
            sharedTunnel?.let {
                runCatching { backend.setState(it, Tunnel.State.DOWN, null) }
                sharedTunnel = null
                delay(150)
            }

            val parsed = Config.parse(ByteArrayInputStream(configString.toByteArray(Charsets.UTF_8)))
            val ifaceBuilder = Interface.Builder()
                .parseAddresses(parsed.`interface`.addresses.joinToString(", ") { it.toString() })
            if (parsed.`interface`.dnsServers.isNotEmpty()) {
                ifaceBuilder.parseDnsServers(parsed.`interface`.dnsServers.joinToString(", ") { it.hostAddress ?: "" })
            }
            ifaceBuilder.parseMtu(
                if (parsed.`interface`.mtu.isPresent) parsed.`interface`.mtu.get().coerceAtLeast(1280).toString() else "1280"
            )
            ifaceBuilder.parsePrivateKey(parsed.`interface`.keyPair.privateKey.toBase64())

            val excluded = mutableSetOf(appContext.packageName)
            listOf("com.vkontakte.android", "com.vk.im", "com.vk.calls").forEach { pkg ->
                if (isInstalled(pkg)) excluded.add(pkg)
            }
            if (excluded.isNotEmpty()) ifaceBuilder.excludeApplications(excluded)

            val peer = parsed.peers.firstOrNull() ?: throw IllegalStateException("No peer in config")
            val peerBuilder = Peer.Builder()
                .parsePublicKey(peer.publicKey.toBase64())
            if (peer.preSharedKey.isPresent) peerBuilder.parsePreSharedKey(peer.preSharedKey.get().toBase64())
            if (peer.endpoint.isPresent) peerBuilder.parseEndpoint(peer.endpoint.get().toString())
            if (peer.persistentKeepalive.isPresent) peerBuilder.parsePersistentKeepalive(peer.persistentKeepalive.get().toString())
            peerBuilder.parseAllowedIPs(generateExclusionAllowedIPs(excludeIPs))

            val finalConfig = Config.Builder()
                .setInterface(ifaceBuilder.build())
                .addPeer(peerBuilder.build())
                .build()

            val tunnel = WgTunnel()
            backend.setState(tunnel, Tunnel.State.UP, finalConfig)
            sharedTunnel = tunnel
            Log.i(TAG, "WireGuard tunnel UP (exclude ${excludeIPs.size} IPs)")
        }
    }

    suspend fun stopTunnel() = wgMutex.withLock {
        withContext(Dispatchers.IO) {
            sharedTunnel?.let {
                runCatching { backend.setState(it, Tunnel.State.DOWN, null) }
                sharedTunnel = null
            }
        }
    }

    private suspend fun ensureGoBackendServiceStarted() {
        withContext(Dispatchers.Main) {
            runCatching {
                appContext.startService(Intent(appContext, GoBackend.VpnService::class.java))
            }
        }
        delay(300)
    }

    private fun isInstalled(pkg: String): Boolean = runCatching {
        appContext.packageManager.getPackageInfo(pkg, 0)
        true
    }.getOrDefault(false)
}
