package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import android.net.VpnService
import androidx.core.content.ContextCompat
import com.google.gson.Gson
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.data.activeServerHashes
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors

object VpnTileConnect {

    enum class ConnectResult {
        Started,
        NeedVpnPermission,
        NeedLogin,
        NoConfig,
        AlreadyConnected,
    }

    private fun repository(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun isVpnActive(): Boolean =
        SilentVpnService.isRunning &&
            (WdttTunnelManager.tunnelReady.value || WdttTunnelManager.running.value)

    fun disconnect(context: Context) {
        context.startService(
            Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            },
        )
    }

    fun tryConnect(context: Context): ConnectResult {
        if (isVpnActive()) return ConnectResult.AlreadyConnected
        val repo = repository(context)
        if (!repo.isLoggedIn()) return ConnectResult.NeedLogin
        val cached = loadCachedConfig(repo) ?: return ConnectResult.NoConfig
        if (VpnService.prepare(context) != null) return ConnectResult.NeedVpnPermission
        startVpnService(context, repo, cached)
        return ConnectResult.Started
    }

    /** После выдачи VPN-разрешения из [TileConnectActivity]. */
    fun connectAfterPermission(context: Context): ConnectResult {
        if (isVpnActive()) return ConnectResult.AlreadyConnected
        val repo = repository(context)
        if (!repo.isLoggedIn()) return ConnectResult.NeedLogin
        val cached = loadCachedConfig(repo) ?: return ConnectResult.NoConfig
        startVpnService(context, repo, cached)
        return ConnectResult.Started
    }

    private fun loadCachedConfig(repo: SilentRepository): VpnConfig? {
        val cached = repo.getCachedVpnConfig() ?: return null
        val parsed = runCatching { Gson().fromJson(cached, VpnConfig::class.java) }.getOrNull() ?: return null
        if (repo.isLoggedIn() && parsed.device_id.startsWith("boot:")) return null
        if (parsed.device_id != repo.getSessionDeviceId()) return null
        if (parsed.vk_hashes.isEmpty() ||
            parsed.wg_private_key.isBlank() ||
            parsed.server_public_key.isBlank()
        ) {
            return null
        }
        return parsed
    }

    private fun resolveMainVpnConfig(repo: SilentRepository, config: VpnConfig): VpnConfig {
        if (!repo.isLoggedIn() || !config.device_id.startsWith("boot:")) return config
        val sessionId = repo.getSessionDeviceId()?.takeIf { it.isNotBlank() && !it.startsWith("boot:") }
            ?: return config
        return config.copy(device_id = sessionId)
    }

    private fun wdttConnectConfig(repo: SilentRepository, config: VpnConfig): VpnConfig {
        val boot = repo.getBootstrapHash()?.trim().orEmpty()
        val filtered = config.copy(
            vk_hashes = config.vk_hashes
                .filter { it.isNotBlank() && it != boot }
                .distinct()
                .take(HashChannelHelper.MAX_HASHES)
                .ifEmpty { config.vk_hashes },
        )
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

    private fun startVpnService(context: Context, repo: SilentRepository, config: VpnConfig) {
        val wdttConfig = wdttConnectConfig(repo, resolveMainVpnConfig(repo, config))
        DebugLog.i("VpnTileConnect", "tile connect device=${wdttConfig.device_id.take(8)} n=${wdttConfig.stream_count}")
        val intent = Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(wdttConfig))
        }
        ContextCompat.startForegroundService(context, intent)
    }
}
