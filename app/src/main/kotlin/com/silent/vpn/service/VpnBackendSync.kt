package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Backend через VPN-туннель — РОВНО один connect-sync за сессию:
 * - ПОСЛЕ tunnelReady: POST /connect + хеши (Wi‑Fi: public/proxy; mobile: proxy/direct, без overlay)
 * - ДО stop VPN: POST /disconnect (tunnel path, с таймаутом)
 *
 * Периодического heartbeat нет: онлайн-статус устройства держит сам wdtt-server.
 */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"
    private const val TUNNEL_WAIT_MS = 60_000L
    /** При неудаче initial sync — повтор через [ensureBackendSyncAfterTunnel] из statsUpdater. */
    private const val RETRY_MIN_INTERVAL_MS = 15_000L
    private const val DISCONNECT_NOTIFY_TIMEOUT_MS = 1_500L

    private var syncJob: Job? = null

    @Volatile
    private var lastAttemptAtMs = 0L

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    /** После поднятия WG: online + хеши — один tunnel-сеанс, без периодических повторов. */
    fun ensureBackendSyncAfterTunnel(scope: CoroutineScope, context: Context) {
        if (VpnSessionState.tunnelDataSyncCompleted) return
        if (syncJob?.isActive == true) return
        val now = System.currentTimeMillis()
        if (now - lastAttemptAtMs < RETRY_MIN_INTERVAL_MS) return
        lastAttemptAtMs = now
        SessionTrace.mark("VpnBackendSync.ensureBackendSyncAfterTunnel")
        syncJob = scope.launch(Dispatchers.IO) {
            if (!waitForTunnel(scope)) return@launch
            if (!repo(context).isLoggedIn() || WdttTunnelManager.isBootstrapMode()) return@launch
            val r = repo(context)
            if (!SilentRepository.APP_EXCLUDED_FROM_VPN) {
                r.prepareMainVpnDirectApi()
            } else {
                r.ensureTunnelApiProxy()
            }
            val ok = runCatching { r.syncAllViaTunnel() }.getOrDefault(false)
            if (ok) {
                VpnSessionState.tunnelDataSyncCompleted = true
                VpnSessionState.backendSyncCompleted = true
                DebugLog.i(TAG, "after tunnel: POST /connect + sync OK")
            } else {
                DebugLog.w(TAG, "after tunnel: POST /connect/sync FAILED — retry in 8s")
                delay(8_000)
                if (
                    scope.isActive &&
                    WdttTunnelManager.tunnelReady.value &&
                    WdttTunnelManager.running.value
                ) {
                    val retryOk = runCatching { r.syncAllViaTunnel() }.getOrDefault(false)
                    if (retryOk) {
                        VpnSessionState.tunnelDataSyncCompleted = true
                        VpnSessionState.backendSyncCompleted = true
                        DebugLog.i(TAG, "after tunnel: retry OK")
                    } else {
                        DebugLog.w(TAG, "after tunnel: retry FAILED")
                        lastAttemptAtMs = 0L
                    }
                } else {
                    lastAttemptAtMs = 0L
                }
            }
        }
    }

    private suspend fun waitForTunnel(scope: CoroutineScope): Boolean {
        val deadline = System.currentTimeMillis() + TUNNEL_WAIT_MS
        while (System.currentTimeMillis() < deadline && scope.isActive) {
            if (!WdttTunnelManager.running.value) return false
            if (WdttTunnelManager.tunnelReady.value) break
            delay(500)
        }
        if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) {
            return false
        }
        // Overlay sync — после ramp-up воркеров, чтобы не сбивать подключение.
        val rampDeadline = System.currentTimeMillis() + 30_000L
        while (System.currentTimeMillis() < rampDeadline && scope.isActive) {
            if (!WdttTunnelManager.running.value) return false
            if (!WdttTunnelManager.isWorkerRampUpActive()) break
            delay(500)
        }
        val workerDeadline = System.currentTimeMillis() + 60_000L
        while (System.currentTimeMillis() < workerDeadline && scope.isActive) {
            if (!WdttTunnelManager.running.value) return false
            if (WdttTunnelManager.activeWorkers.value >= 1) {
                return WdttTunnelManager.tunnelReady.value
            }
            if (!WdttTunnelManager.isLibclientProcessAlive()) return false
            delay(400)
        }
        return WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            WdttTunnelManager.activeWorkers.value >= 1
    }

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
        syncJob?.cancel()
        syncJob = null
        lastAttemptAtMs = 0L
        VpnSessionState.resetBackendSync()
    }

    /** ДО stopAndAwait — тот же tunnel path, что connect; жёсткий таймаут, чтобы disconnect не висел. */
    suspend fun notifyDisconnect(context: Context) {
        if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) {
            DebugLog.w(TAG, "disconnect skipped — tunnel not up")
            return
        }
        val ok = withTimeoutOrNull(DISCONNECT_NOTIFY_TIMEOUT_MS) {
            runCatching { repo(context).notifyDisconnectBeforeTunnelStop() }.getOrDefault(false)
        } ?: false
        if (ok) DebugLog.i(TAG, "before stop: disconnect OK") else DebugLog.w(TAG, "before stop: disconnect FAILED/timeout")
    }
}
