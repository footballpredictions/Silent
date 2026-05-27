package com.silent.vpn.vpn

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.util.Log
import com.silent.vpn.util.DebugLog
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

/** WireGuard через GoBackend — как в proxy-turn-vk-android. */
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
                if (parsed.`interface`.mtu.isPresent) parsed.`interface`.mtu.get().coerceAtLeast(1280).toString()
                else "1280"
            )
            ifaceBuilder.parsePrivateKey(parsed.`interface`.keyPair.privateKey.toBase64())

            // Исключаем WDTT и VK из туннеля (reference: checked = excluded в обоих режимах)
            val excluded = mutableSetOf(appContext.packageName, "com.vkontakte.android", "com.vk.calls")
            runCatching {
                val repoPrefs = appContext.getSharedPreferences("silent_prefs", Context.MODE_PRIVATE)
                val saved = repoPrefs.getString("excluded_apps", "")?.split(",")?.filter { it.isNotBlank() } ?: emptyList()
                excluded.addAll(saved)
            }
            val installedExcluded = excluded.filter { isInstalled(it) }.toSet()
            if (installedExcluded.isNotEmpty()) ifaceBuilder.excludeApplications(installedExcluded)

            val peer = parsed.peers.firstOrNull() ?: throw IllegalStateException("No peer in config")
            val peerBuilder = Peer.Builder().parsePublicKey(peer.publicKey.toBase64())
            if (peer.preSharedKey.isPresent) peerBuilder.parsePreSharedKey(peer.preSharedKey.get().toBase64())
            if (peer.endpoint.isPresent) peerBuilder.parseEndpoint(peer.endpoint.get().toString())
            if (peer.persistentKeepalive.isPresent) {
                peerBuilder.parsePersistentKeepalive(peer.persistentKeepalive.get().toString())
            }
            peerBuilder.parseAllowedIPs("0.0.0.0/0")

            val finalConfig = Config.Builder()
                .setInterface(ifaceBuilder.build())
                .addPeer(peerBuilder.build())
                .build()

            val tunnel = WgTunnel()
            setTunnelUpWithRetry(tunnel, finalConfig)
            sharedTunnel = tunnel
            Log.i(TAG, "WireGuard tunnel UP")
            DebugLog.i(TAG, "WireGuard tunnel UP")
        }
    }

    private suspend fun setTunnelUpWithRetry(tunnel: WgTunnel, config: Config) {
        var last: Exception? = null
        repeat(3) { attempt ->
            try {
                backend.setState(tunnel, Tunnel.State.UP, config)
                return
            } catch (e: Exception) {
                last = e
                Log.w(TAG, "WG UP attempt ${attempt + 1}/3: ${e.message}")
                DebugLog.w(TAG, "WG UP attempt ${attempt + 1}/3: ${e.message}")
                runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
                ensureGoBackendServiceStarted()
                delay(250L * (attempt + 1))
            }
        }
        throw last ?: IllegalStateException("WireGuard UP failed")
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
