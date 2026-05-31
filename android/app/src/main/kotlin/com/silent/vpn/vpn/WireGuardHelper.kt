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

/**
 * WireGuard: split-tunnel (сервер/TURN вне WG), VK — excludeApplications, API — через WG-шлюз.
 */
class WireGuardHelper(context: Context) {
    private val appContext = context.applicationContext
    private val backend = (appContext as SilentApp).getBackend(context)

    private companion object {
        val wgMutex = Mutex()
        var sharedTunnel: WgTunnel? = null
        var lastAppliedSemanticKey: String? = null
        private const val TAG = "WireGuardHelper"
    }

    class WgTunnel : Tunnel {
        override fun getName() = "silent"
        override fun onStateChange(newState: Tunnel.State) {}
    }

    suspend fun startTunnel(configString: String, excludeIPs: Collection<String> = emptyList(), isBootstrap: Boolean = false) = wgMutex.withLock {
        withContext(Dispatchers.IO) {
            if (VpnService.prepare(appContext) != null) {
                throw IllegalStateException("VPN-разрешение не выдано")
            }
            if (VpnNetworkHelper.isOtherVpnActive(appContext)) {
                DebugLog.i(TAG, "Замена другого VPN — поднимаем Silent")
            }
            ensureGoBackendServiceStarted()

            var configToApply = configString
            if (excludeIPs.isNotEmpty()) {
                configToApply = AllowedIpsHelper.patchAllowedIPs(configString, excludeIPs)
                DebugLog.i(TAG, "Split-tunnel: исключено IP=${excludeIPs.size}")
            }

            val semanticKey = wgSemanticKey(configToApply)
            if (sharedTunnel != null && semanticKey.isNotBlank() && semanticKey == lastAppliedSemanticKey) {
                DebugLog.i(TAG, "WireGuard skip (same config, tunnel UP)")
                return@withContext
            }

            sharedTunnel?.let {
                runCatching { backend.setState(it, Tunnel.State.DOWN, null) }
                sharedTunnel = null
                lastAppliedSemanticKey = null
                delay(150)
            }

            val parsed = Config.parse(ByteArrayInputStream(configToApply.toByteArray(Charsets.UTF_8)))
            val ifaceBuilder = Interface.Builder()
                .parseAddresses(parsed.`interface`.addresses.joinToString(", ") { it.toString() })
            val mtu = if (parsed.`interface`.mtu.isPresent) {
                parsed.`interface`.mtu.get().coerceAtLeast(1280)
            } else {
                1280
            }
            ifaceBuilder.parseMtu(mtu.toString())
            ifaceBuilder.parsePrivateKey(parsed.`interface`.keyPair.privateKey.toBase64())

            runCatching {
                val excluded = resolveExcludedAppPackages(appContext, isBootstrap)
                if (excluded.isNotEmpty()) {
                    ifaceBuilder.excludeApplications(excluded)
                    DebugLog.i(TAG, "App exclusions: ${excluded.size} пакетов вне туннеля (bootstrap=$isBootstrap)")
                }
            }

            val peer = parsed.peers.firstOrNull() ?: throw IllegalStateException("No peer in config")
            val peerBuilder = Peer.Builder().parsePublicKey(peer.publicKey.toBase64())
            if (peer.preSharedKey.isPresent) peerBuilder.parsePreSharedKey(peer.preSharedKey.get().toBase64())
            if (peer.endpoint.isPresent) peerBuilder.parseEndpoint(peer.endpoint.get().toString())
            if (peer.persistentKeepalive.isPresent) {
                peerBuilder.parsePersistentKeepalive(peer.persistentKeepalive.get().toString())
            } else {
                peerBuilder.parsePersistentKeepalive("25")
            }
            val allowedIps = peer.allowedIps.takeIf { it.isNotEmpty() }?.joinToString(", ") { it.toString() }
                ?: if (excludeIPs.isNotEmpty()) AllowedIpsHelper.generateExclusionAllowedIPs(excludeIPs) else "0.0.0.0/0"
            peerBuilder.parseAllowedIPs(allowedIps)
            DebugLog.i(TAG, "AllowedIPs=$allowedIps MTU=$mtu")

            // Используем DNS из конфига (как в proxy-turn-vk-android), fallback = Yandex+Cloudflare.
            // НЕ переопределяем на gateway (10.66.66.1) — на нём нет DNS-сервера → таймаут → YouTube не работает.
            if (parsed.`interface`.dnsServers.isNotEmpty()) {
                ifaceBuilder.parseDnsServers(
                    parsed.`interface`.dnsServers.joinToString(", ") { it.hostAddress ?: "" },
                )
            } else {
                ifaceBuilder.parseDnsServers("1.1.1.1,77.88.8.8")
            }

            val finalConfig = Config.Builder()
                .setInterface(ifaceBuilder.build())
                .addPeer(peerBuilder.build())
                .build()

            val tunnel = WgTunnel()
            setTunnelUpWithRetry(tunnel, finalConfig)
            sharedTunnel = tunnel
            lastAppliedSemanticKey = semanticKey
            Log.i(TAG, "WireGuard tunnel UP")
            DebugLog.i(TAG, "WireGuard tunnel UP")
        }
    }

    private fun wgSemanticKey(config: String): String {
        fun field(name: String): String =
            Regex("""(?m)^$name\s*=\s*(\S+)""").find(config)?.groupValues?.getOrNull(1)?.trim().orEmpty()
        return listOf(
            field("PrivateKey"),
            field("Address"),
            field("PublicKey"),
            field("Endpoint"),
        ).joinToString("|")
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
                lastAppliedSemanticKey = null
            }
        }
    }

    /** Проверяет состояние WG-туннеля через backend (без TCP-соединений — работает даже если app исключён из VPN). */
    fun isTunnelUp(): Boolean {
        val tunnel = sharedTunnel ?: return false
        return runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)
    }

    private suspend fun ensureGoBackendServiceStarted() {
        withContext(Dispatchers.Main) {
            runCatching {
                appContext.startService(Intent(appContext, GoBackend.VpnService::class.java))
            }
        }
        delay(300)
    }
}
