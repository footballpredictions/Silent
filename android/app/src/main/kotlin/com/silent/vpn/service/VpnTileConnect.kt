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

    private const val CONNECT_DEBOUNCE_MS = 2_000L
    private const val DISCONNECT_DEBOUNCE_MS = 800L
    private var lastConnectMs = 0L
    private var lastDisconnectMs = 0L

    private fun repository(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun isVpnActive(context: Context): Boolean = VpnSessionState.isActive()

    fun isSessionBusy(context: Context): Boolean = VpnSessionState.isBusy()

    fun canDisconnectFromTile(context: Context): Boolean = VpnSessionState.canDisconnectFromTile()

    fun isCaptchaPending(): Boolean = VpnSessionState.isCaptchaPending()

    fun disconnect(context: Context) {
        val now = System.currentTimeMillis()
        if (now - lastDisconnectMs < DISCONNECT_DEBOUNCE_MS) {
            SessionTrace.mark("VpnTileConnect.disconnect", "debounced")
            return
        }
        lastDisconnectMs = now
        SessionTrace.enter("VpnTileConnect.disconnect")
        VpnServiceTracker.markSessionActive(context.applicationContext, false)
        context.startService(
            Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            },
        )
        VpnTileHelper.requestUpdate(context.applicationContext)
    }

    fun tryConnect(context: Context): ConnectResult {
        SessionTrace.enter("VpnTileConnect.tryConnect")
        val appCtx = context.applicationContext
        val now = System.currentTimeMillis()
        if (now - lastConnectMs < CONNECT_DEBOUNCE_MS) {
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
        lastConnectMs = now
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
        lastConnectMs = System.currentTimeMillis()
        startVpnService(context, repo, cached)
        SessionTrace.exit("VpnTileConnect.connectAfterPermission", "started")
        return ConnectResult.Started
    }

    /** Только START_STICKY в том же процессе — не вызывать из Application.onCreate. */
    fun restartCachedSession(context: Context): Boolean {
        SessionTrace.enter("VpnTileConnect.restartCachedSession")
        if (VpnSessionState.isActive()) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "already active")
            return true
        }
        if (VpnSessionState.isBusy()) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "busy")
            return false
        }
        if (!VpnServiceTracker.isSessionMarkedActive(context)) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "pref inactive")
            return false
        }
        val repo = repository(context)
        if (!repo.isLoggedIn()) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "not logged in")
            VpnServiceTracker.markSessionActive(context, false)
            return false
        }
        val cached = loadCachedConfig(repo)
        if (cached == null) {
            SessionTrace.exit("VpnTileConnect.restartCachedSession", "no config")
            VpnServiceTracker.markSessionActive(context, false)
            return false
        }
        SessionTrace.mark("VpnTileConnect.restartCachedSession", "starting service")
        startVpnService(context, repo, cached)
        SessionTrace.exit("VpnTileConnect.restartCachedSession", "started")
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
