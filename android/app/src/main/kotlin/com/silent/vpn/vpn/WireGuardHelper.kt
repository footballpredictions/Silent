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
    }

    class WgTunnel : Tunnel {
        override fun getName() = "silent"
        override fun onStateChange(newState: Tunnel.State) {}
    }

    suspend fun startTunnel(configString: String) = wgMutex.withLock {
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
            peerBuilder.parseAllowedIPs("0.0.0.0/0")

            val finalConfig = Config.Builder()
                .setInterface(ifaceBuilder.build())
                .addPeer(peerBuilder.build())
                .build()

            val tunnel = WgTunnel()
            backend.setState(tunnel, Tunnel.State.UP, finalConfig)
            sharedTunnel = tunnel
            Log.i(TAG, "WireGuard tunnel UP")
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
