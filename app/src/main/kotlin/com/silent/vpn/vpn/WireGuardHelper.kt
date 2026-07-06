package com.silent.vpn.vpn



import android.content.Context

import android.content.Intent

import android.net.VpnService

import android.util.Log

import com.silent.vpn.util.DebugLog

import com.silent.vpn.SilentApp
import com.silent.vpn.data.BootstrapVpnConfig
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentGoBackendVpnService

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

 * WireGuard: split-tunnel (сервер/TURN вне WG), VK — excludeApplications.
 * Bootstrap: includeApplications (Silent + браузеры + почта), AllowedIPs → API + backend HTTPS.
 * apiOverlayMode: кратко AllowedIPs = 10.66.66.0/24 для sync API.
 */

class WireGuardHelper(context: Context) {

    private val appContext = context.applicationContext

    private val backend = (appContext as SilentApp).getBackend(context)



    companion object {

        val wgMutex = Mutex()

        var sharedTunnel: WgTunnel? = null

        var lastAppliedSemanticKey: String? = null

        @Volatile var wgTransitionActive: Boolean = false

        private const val TAG = "WireGuardHelper"

        fun isWgTransitionActive(): Boolean = wgTransitionActive

    }
    suspend fun forceStopSilentTunnel() = wgMutex.withLock {
        withContext(Dispatchers.IO) {
            runCatching {
                appContext.startService(Intent(appContext, SilentGoBackendVpnService::class.java))
            }
            delay(300)
            val tunnel = sharedTunnel ?: WgTunnel()
            runCatching { backend.setState(tunnel, Tunnel.State.DOWN, null) }
            sharedTunnel = null
            lastAppliedSemanticKey = null
        }
    }

    class WgTunnel : Tunnel {

        override fun getName() = "silent"

        override fun onStateChange(newState: Tunnel.State) {}

    }



    suspend fun startTunnel(

        configString: String,

        excludeIPs: Collection<String> = emptyList(),

        isBootstrap: Boolean = false,

        apiOverlayMode: Boolean = false,

        mobileApiRoute: Boolean = false,

    ) = wgMutex.withLock {

        withContext(Dispatchers.IO) {
            wgTransitionActive = true
            try {

            if (VpnService.prepare(appContext) != null) {

                throw IllegalStateException("VPN-разрешение не выдано")

            }

            if (VpnNetworkHelper.isOtherVpnActive(appContext)) {

                DebugLog.i(TAG, "Замена другого VPN — поднимаем Silent")

            }

            ensureGoBackendServiceStarted()



            var configToApply = configString

            if (!apiOverlayMode) {
                if (isBootstrap) {
                    configToApply = if (excludeIPs.isNotEmpty()) {
                        AllowedIpsHelper.patchAllowedIPs(configString, excludeIPs).also {
                            DebugLog.i(TAG, "Bootstrap AllowedIPs: 0.0.0.0/0 − ${excludeIPs.size} host(s)")
                        }
                    } else {
                        AllowedIpsHelper.patchAllowedIPsForBootstrapAuth(
                            configString,
                            serverIpFromConfig(configString),
                        ).also {
                            DebugLog.i(TAG, "Bootstrap AllowedIPs: API + backend HTTPS")
                        }
                    }
                } else if (excludeIPs.isNotEmpty()) {
                    configToApply = AllowedIpsHelper.patchAllowedIPs(configString, excludeIPs).also {
                        DebugLog.i(TAG, "Main AllowedIPs: 0.0.0.0/0 − ${excludeIPs.size} host(s)")
                    }
                }
                if (!isBootstrap && mobileApiRoute) {
                    configToApply = AllowedIpsHelper.patchAllowedIPsEnsureApiSubnet(configToApply).also {
                        DebugLog.i(TAG, "Main mobile: +${AllowedIpsHelper.WG_TUNNEL_SUBNET} for API (no overlay)")
                    }
                }
            } else {
                configToApply = AllowedIpsHelper.patchAllowedIPsToSubnet(configString)
                DebugLog.i(TAG, "API overlay: ${AllowedIpsHelper.WG_TUNNEL_SUBNET}")
            }



            val excludeKey = when {
                isBootstrap && !apiOverlayMode -> "bootstrap-companion"
                apiOverlayMode -> "overlay-app-in"
                mobileApiRoute -> "mobile-api-${excludeIPs.sorted().joinToString(",")}"
                else -> excludeIPs.sorted().joinToString(",")
            }

            val semanticKey = wgSemanticKey(configToApply) + "|ex=$excludeKey|ov=$apiOverlayMode"

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



            val normalizedConfig = normalizeInterfaceConfig(configToApply)
            val parsed = Config.parse(ByteArrayInputStream(normalizedConfig.toByteArray(Charsets.UTF_8)))

            val ifaceBuilder = Interface.Builder()

                .parseAddresses(parsed.`interface`.addresses.joinToString(", ") { it.toString() })

            val mtu = if (parsed.`interface`.mtu.isPresent) {

                parsed.`interface`.mtu.get().coerceAtLeast(1280)

            } else {

                1280

            }

            ifaceBuilder.parseMtu(mtu.toString())

            ifaceBuilder.parsePrivateKey(parsed.`interface`.keyPair.privateKey.toBase64())



            if (isBootstrap && !apiOverlayMode) {
                runCatching {
                    val included = resolveBootstrapIncludedApps(appContext)
                    if (included.isNotEmpty()) {
                        ifaceBuilder.includeApplications(included)
                        DebugLog.i(TAG, "Bootstrap includeApplications: ${included.size}")
                    }
                }
            } else {
                val includeAppInTunnel = apiOverlayMode || !SilentRepository.APP_EXCLUDED_FROM_VPN
                runCatching {
                    val excluded = resolveExcludedAppPackages(appContext, includeAppInTunnel)
                    if (excluded.isNotEmpty()) {
                        ifaceBuilder.excludeApplications(excluded)
                        DebugLog.i(TAG, "App exclusions: ${excluded.size} (bootstrap=$isBootstrap overlay=$apiOverlayMode)")
                    }
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

            val allowedIps = parsed.peers.firstOrNull()?.allowedIps?.takeIf { it.isNotEmpty() }
                ?.joinToString(", ") { it.toString() }
                ?: "0.0.0.0/0"

            peerBuilder.parseAllowedIPs(allowedIps)

            DebugLog.i(TAG, "AllowedIPs=$allowedIps MTU=$mtu")



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



            val tunnel = sharedTunnel
            if (tunnel != null) {
                runCatching {
                    backend.setState(tunnel, Tunnel.State.UP, finalConfig)
                    lastAppliedSemanticKey = semanticKey
                    DebugLog.i(TAG, "WireGuard hot reload")
                    return@withContext
                }.onFailure { e ->
                    DebugLog.w(TAG, "WG hot reload failed: ${e.message}")
                }
            }

            sharedTunnel?.let {

                runCatching { backend.setState(it, Tunnel.State.DOWN, null) }

                sharedTunnel = null

                lastAppliedSemanticKey = null

                delay(150)

            }



            val newTunnel = WgTunnel()

            setTunnelUpWithRetry(newTunnel, finalConfig)

            sharedTunnel = newTunnel

            lastAppliedSemanticKey = semanticKey

            Log.i(TAG, "WireGuard tunnel UP")

            DebugLog.i(TAG, "WireGuard tunnel UP")

            } finally {
                wgTransitionActive = false
            }
        }

    }



    private fun serverIpFromConfig(config: String): String {
        val endpoint = Regex("""(?m)^Endpoint\s*=\s*([^:\s]+)""")
            .find(config)?.groupValues?.getOrNull(1)?.trim().orEmpty()
        if (endpoint.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) &&
            endpoint != "127.0.0.1" &&
            endpoint != "0.0.0.0"
        ) {
            return endpoint
        }
        return BootstrapVpnConfig.serverHost()
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

    private fun normalizeInterfaceConfig(config: String): String {
        var addressPatched = false
        var dnsPatched = false
        val lines = config.lines().map { line ->
            val trimmed = line.trimStart()
            when {
                trimmed.startsWith("Address", ignoreCase = true) && line.contains("=") -> {
                    val prefix = line.substringBefore("=")
                    val raw = line.substringAfter("=").trim()
                    val normalized = normalizeAddressList(raw)
                    if (normalized != null && normalized != raw) {
                        addressPatched = true
                        "$prefix= $normalized"
                    } else {
                        line
                    }
                }
                trimmed.startsWith("DNS", ignoreCase = true) && line.contains("=") -> {
                    val prefix = line.substringBefore("=")
                    val raw = line.substringAfter("=").trim()
                    val normalized = normalizeDnsList(raw)
                    if (normalized != raw) {
                        dnsPatched = true
                        "$prefix= $normalized"
                    } else {
                        line
                    }
                }
                else -> line
            }
        }
        if (addressPatched || dnsPatched) {
            DebugLog.w(TAG, "WireGuard config normalized before parse (address=$addressPatched dns=$dnsPatched)")
        }
        return lines.joinToString("\n")
    }

    private fun normalizeAddressList(raw: String): String? {
        val tokens = raw.split(",")
            .map { it.trim() }
            .filter { it.isNotBlank() }
        if (tokens.isEmpty()) return null
        val normalized = tokens.mapNotNull { token ->
            when {
                IPV4_CIDR.matches(token) -> sanitizeIpv4CidrToken(token)
                IPV4.matches(token) -> sanitizeIpv4CidrToken("$token/32")
                IPV6_CIDR.matches(token) -> token
                IPV6.matches(token) -> "$token/128"
                else -> null
            }
        }
        return normalized.takeIf { it.isNotEmpty() }?.joinToString(", ")
    }

    private fun sanitizeIpv4CidrToken(token: String): String? {
        val parts = token.split("/")
        if (parts.size != 2) return null
        val ip = parts[0].trim()
        var prefix = parts[1].trim().toIntOrNull() ?: return null
        if (prefix !in 0..32) prefix = 32

        val octets = ip.split(".").map { it.toIntOrNull() ?: return null }
        if (octets.size != 4) return null
        if (octets.any { it !in 0..255 }) return null

        val fixed = octets.toMutableList()
        // Android VPN stack может падать с "Bad address" на сетевом адресе (например x.x.x.0/24).
        // Для интерфейса WireGuard принудительно переводим такой адрес в хостовый.
        if (prefix < 32 && fixed[3] == 0) {
            fixed[3] = 2
        }
        if (prefix == 0) prefix = 32
        return "${fixed[0]}.${fixed[1]}.${fixed[2]}.${fixed[3]}/$prefix"
    }

    private fun normalizeDnsList(raw: String): String {
        val tokens = raw.split(",")
            .map { it.trim() }
            .filter { it.isNotBlank() }
        val normalized = tokens.filter { IPV4.matches(it) || IPV6.matches(it) }
        return if (normalized.isNotEmpty()) normalized.joinToString(", ") else "1.1.1.1, 77.88.8.8"
    }

    private val IPV4 = Regex("""^\d{1,3}(\.\d{1,3}){3}$""")
    private val IPV4_CIDR = Regex("""^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$""")
    private val IPV6 = Regex("""^[0-9a-fA-F:]+$""")
    private val IPV6_CIDR = Regex("""^[0-9a-fA-F:]+/(12[0-8]|1[01][0-9]|[1-9]?[0-9])$""")



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



    fun isTunnelUp(): Boolean {

        val tunnel = sharedTunnel ?: return false

        return runCatching { backend.getState(tunnel) == Tunnel.State.UP }.getOrDefault(false)

    }



    private suspend fun ensureGoBackendServiceStarted() {

        withContext(Dispatchers.Main) {

            runCatching {

                appContext.startService(Intent(appContext, SilentGoBackendVpnService::class.java))

            }

        }

        delay(300)

    }

}


