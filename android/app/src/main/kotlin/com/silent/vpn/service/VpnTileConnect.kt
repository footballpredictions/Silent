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
import com.silent.vpn.util.SessionTrace
import dagger.hilt.android.EntryPointAccessors

object VpnTileConnect {

    enum class ConnectResult {
        Started,
        NeedVpnPermission,
        NeedLogin,
        NoConfig,
        AlreadyConnected,
        Busy,
    }

    private const val TILE_DEBOUNCE_MS = 4_000L
    private var lastTileActionMs = 0L

    private fun repository(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun isVpnActive(context: Context): Boolean =
        VpnSessionState.isActive(context.applicationContext)

    fun isSessionBusy(context: Context): Boolean =
        VpnSessionState.isBusy(context.applicationContext)

    fun isCaptchaPending(): Boolean = VpnSessionState.isCaptchaPending()

    fun disconnect(context: Context) {
        val now = System.currentTimeMillis()
        if (now - lastTileActionMs < TILE_DEBOUNCE_MS) {
            SessionTrace.mark("VpnTileConnect.disconnect", "debounced")
            return
        }
        lastTileActionMs = now
        SessionTrace.enter("VpnTileConnect.disconnect")
        context.startService(
            Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            },
        )
    }

    fun tryConnect(context: Context): ConnectResult {
        SessionTrace.enter("VpnTileConnect.tryConnect")
        val appCtx = context.applicationContext
        val now = System.currentTimeMillis()
        if (now - lastTileActionMs < TILE_DEBOUNCE_MS) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "debounced")
            DebugLog.i("VpnTileConnect", "tile connect debounced")
            return ConnectResult.Busy
        }
        if (isVpnActive(context)) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "already connected")
            return ConnectResult.AlreadyConnected
        }
        if (isSessionBusy(context)) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "session busy")
            DebugLog.i("VpnTileConnect", "tile connect blocked — session busy")
            return ConnectResult.Busy
        }
        val repo = repository(context)
        if (!repo.isLoggedIn()) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "need login")
            return ConnectResult.NeedLogin
        }
        val cached = loadCachedConfig(repo)
        if (cached == null) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "no config")
            return ConnectResult.NoConfig
        }
        if (VpnService.prepare(context) != null) {
            SessionTrace.exit("VpnTileConnect.tryConnect", "need vpn permission")
            return ConnectResult.NeedVpnPermission
        }
        lastTileActionMs = now
        SessionTrace.mark("VpnTileConnect.tryConnect", "starting service")
        startVpnService(context, repo, cached)
        SessionTrace.exit("VpnTileConnect.tryConnect", "started")
        return ConnectResult.Started
    }

    /** После выдачи VPN-разрешения из [TileConnectActivity]. */
    fun connectAfterPermission(context: Context): ConnectResult {
        SessionTrace.enter("VpnTileConnect.connectAfterPermission")
        if (isVpnActive(context)) {
            SessionTrace.exit("VpnTileConnect.connectAfterPermission", "already connected")
            return ConnectResult.AlreadyConnected
        }
        if (isSessionBusy(context)) {
            SessionTrace.exit("VpnTileConnect.connectAfterPermission", "busy")
            return ConnectResult.Busy
        }
        val repo = repository(context)
        if (!repo.isLoggedIn()) {
            SessionTrace.exit("VpnTileConnect.connectAfterPermission", "need login")
            return ConnectResult.NeedLogin
        }
        val cached = loadCachedConfig(repo)
        if (cached == null) {
            SessionTrace.exit("VpnTileConnect.connectAfterPermission", "no config")
            return ConnectResult.NoConfig
        }
        lastTileActionMs = System.currentTimeMillis()
        startVpnService(context, repo, cached)
        SessionTrace.exit("VpnTileConnect.connectAfterPermission", "started")
        return ConnectResult.Started
    }

    /** Переподключение после START_STICKY (процесс убит, сервис перезапущен). */
    fun restartCachedSession(context: Context): Boolean {
        SessionTrace.enter("VpnTileConnect.restartCachedSession")
        if (VpnSessionState.isActive(context)) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "already active")
            return true
        }
        if (VpnSessionState.isBusy(context)) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "busy")
            return false
        }
        val started = restartCachedSessionDirect(context)
        SessionTrace.exit("VpnTileConnect.restartCachedSession", if (started) "started" else "failed")
        return started
    }

    /** Без reconcileStaleSession — для восстановления после убийства процесса. */
    internal fun restartCachedSessionDirect(context: Context): Boolean {
        SessionTrace.enter("VpnTileConnect.restartCachedSessionDirect")
        if (SilentVpnService.isRunning || WdttTunnelManager.running.value) {
            SessionTrace.exit("VpnTileConnect.restartCachedSessionDirect", "busy")
            return false
        }
        val repo = repository(context)
        if (!repo.isLoggedIn()) {
            SessionTrace.exit("VpnTileConnect.restartCachedSessionDirect", "not logged in")
            VpnServiceTracker.markSessionActive(context, false)
            return false
        }
        val cached = loadCachedConfig(repo)
        if (cached == null) {
            SessionTrace.exit("VpnTileConnect.restartCachedSessionDirect", "no config")
            VpnServiceTracker.markSessionActive(context, false)
            return false
        }
        SessionTrace.mark("VpnTileConnect.restartCachedSessionDirect", "starting service")
        startVpnService(context, repo, cached)
        SessionTrace.exit("VpnTileConnect.restartCachedSessionDirect", "started")
        return true
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
