package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import com.google.gson.Gson
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.data.activeServerHashes
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.VpnNetworkHelper
import dagger.hilt.android.EntryPointAccessors
import org.json.JSONObject

/** Кеш конфига → CONNECT intent (как prepareVpnConnectConfig + vpnConnect на PC). */
object VpnTileConnect {

    private const val TAG = "VpnTileConnect"

    fun isCaptchaPending(): Boolean = VpnSessionState.isCaptchaPending()

    /** Старт VPN из кеша — без сетевых вызовов (как buildStartIntent в reference). */
    fun buildConnectIntentFromCache(context: Context): Intent? {
        val repo = repository(context)
        if (!repo.isLoggedIn()) return null
        if (repo.isOlcrtcBypass()) {
            return buildOlcrtcConnectIntent(context, repo)
        }
        val config = loadCachedConfig(repo) ?: return null
        return buildConnectIntent(context, repo, config)
    }

    private fun buildOlcrtcConnectIntent(context: Context, repo: SilentRepository): Intent? {
        val olc = repo.getCachedOlcrtcConfig() ?: run {
            DebugLog.w(TAG, "olcrtc tile: no cached config")
            return null
        }
        val provider = repo.getOlcrtcProvider()
        val p = olc.providers[provider]
        if (p?.denied == true || (olc.pool_denied && p?.room.isNullOrBlank())) {
            DebugLog.w(TAG, "olcrtc tile: pool denied")
            return null
        }
        if (!olc.enabled || olc.crypto_key.length != 64 || p == null || !p.enabled || p.room.isBlank()) {
            DebugLog.w(TAG, "olcrtc tile: incomplete config provider=$provider")
            return null
        }
        val deviceId = repo.getSessionDeviceId()?.takeIf { it.isNotBlank() } ?: "android"
        val json = JSONObject().apply {
            put("bypass_family", "olcrtc")
            put("bypassFamily", "olcrtc2")
            put("olcrtc_provider", provider)
            put("olcrtc_room", p.room)
            put("olcrtc_crypto_key", olc.crypto_key)
            put("olcrtc_transport", p.transport.ifBlank { "datachannel" })
            put("olcrtc_socks_host", olc.socks_host.ifBlank { "127.0.0.1" })
            put("olcrtc_socks_port", olc.socks_port.takeIf { it > 0 } ?: 8808)
            if (p.auth_token.isNotBlank()) {
                put("olcrtc_auth_token", p.auth_token)
            }
            if (
                VpnNetworkHelper.isOnMobileData(context) &&
                olc.jitsi_https_proxy.isNotBlank() &&
                (p.room.contains("meet.egovm.ru") || p.room.contains("meet.playform.ru"))
            ) {
                put("olcrtc_https_proxy", olc.jitsi_https_proxy)
            }
            put("is_bootstrap", false)
            put("device_id", deviceId)
        }
        DebugLog.i(TAG, "CONNECT olcrtc provider=$provider room=${p.room.take(32)}")
        return Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, json.toString())
            putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, false)
            putExtra(SilentVpnService.EXTRA_FROM_TILE, true)
        }
    }

    private fun buildConnectIntent(
        context: Context,
        repo: SilentRepository,
        config: VpnConfig,
    ): Intent? {
        if (!isConfigConnectable(repo, config)) return null
        val wdttConfig = wdttConnectConfig(repo, config)
        DebugLog.i(
            TAG,
            "CONNECT device=${wdttConfig.device_id.take(8)} n=${wdttConfig.stream_count} vk=${wdttConfig.vk_hashes.size}",
        )
        return Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(wdttConfig))
            putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, false)
            putExtra(SilentVpnService.EXTRA_FROM_TILE, true)
            putExtra(SilentVpnService.EXTRA_REQUIRE_GETCONF, false)
        }
    }

    private fun repository(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    private fun loadCachedConfig(repo: SilentRepository): VpnConfig? {
        val cached = repo.getCachedVpnConfig() ?: return null
        val parsed = runCatching { Gson().fromJson(cached, VpnConfig::class.java) }.getOrNull() ?: return null
        var config = resolveMainVpnConfig(repo, parsed)
        if (repo.isLoggedIn() && config.device_id.startsWith("boot:")) return null
        val sessionId = repo.getSessionDeviceId()
        if (!sessionId.isNullOrBlank() && config.device_id != sessionId) {
            config = config.copy(device_id = sessionId)
        }
        if (!isConfigConnectable(repo, config)) return null
        return config
    }

    private fun isConfigConnectable(repo: SilentRepository, config: VpnConfig): Boolean {
        val hasHashes = repo.resolveConnectVkHashes(config.vk_hashes).isNotEmpty() ||
            repo.getSavedHashItems().activeServerHashes().isNotEmpty()
        return hasHashes &&
            config.wg_private_key.isNotBlank() &&
            config.server_public_key.isNotBlank()
    }

    private fun resolveMainVpnConfig(repo: SilentRepository, config: VpnConfig): VpnConfig {
        if (!repo.isLoggedIn() || !config.device_id.startsWith("boot:")) return config
        val sessionId = repo.getSessionDeviceId()?.takeIf { it.isNotBlank() && !it.startsWith("boot:") }
            ?: return config
        return config.copy(device_id = sessionId)
    }

    private fun wdttConnectConfig(repo: SilentRepository, config: VpnConfig): VpnConfig {
        val filtered = config.copy(vk_hashes = repo.resolveConnectVkHashes(config.vk_hashes))
        val activeHashes = maxOf(
            filtered.vk_hashes.size,
            repo.getSavedHashItems().activeServerHashes().size,
            1,
        ).coerceAtMost(HashChannelHelper.MAX_HASHES)
        val workers = repo.resolveWorkersForLibclient(activeHashes)
        val hashes = HashChannelHelper.hashesForLibclient(filtered.vk_hashes, workers)
        return filtered.copy(
            vk_hashes = hashes.ifEmpty { filtered.vk_hashes },
            stream_count = workers,
        )
    }
}
