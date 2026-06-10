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

/**
 * Backend через VPN-туннель (overlay → 10.66.66.1):
 * - ПОСЛЕ tunnelReady: POST /connect + хеши
 * - ДО stop VPN: POST /disconnect
 */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"
    private const val HEARTBEAT_MS = 15 * 60_000L
    private const val TUNNEL_WAIT_MS = 60_000L

    private var syncJob: Job? = null

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    /** После поднятия WG: online + хеши (один tunnel-сеанс). */
    fun ensureBackendSyncAfterTunnel(scope: CoroutineScope, context: Context) {
        if (syncJob?.isActive == true) return
        SessionTrace.mark("VpnBackendSync.ensureBackendSyncAfterTunnel")
        syncJob = scope.launch(Dispatchers.IO) {
            if (!waitForTunnel(scope)) return@launch
            if (!repo(context).isLoggedIn() || WdttTunnelManager.isBootstrapMode()) return@launch
            val r = repo(context)
            val ok = runCatching { r.syncAllViaTunnel() }.getOrDefault(false)
            if (ok) {
                VpnSessionState.tunnelDataSyncCompleted = true
                DebugLog.i(TAG, "after tunnel: connect+hashes OK")
            } else {
                DebugLog.w(TAG, "after tunnel: connect+hashes FAILED — retry in 5s")
                delay(5_000)
                if (WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value) {
                    runCatching { r.syncHashesViaTunnel() }
                        .onSuccess { if (it) DebugLog.i(TAG, "hashes retry OK") }
                }
            }
            while (isActive && WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value) {
                delay(HEARTBEAT_MS)
                if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) break
                if (!repo(context).isLoggedIn()) break
                runCatching { r.pingOnlineWithBackend() }
                    .onSuccess { if (it) DebugLog.i(TAG, "heartbeat OK") }
            }
        }
    }

    fun ensureOnlineAfterTunnel(scope: CoroutineScope, context: Context) =
        ensureBackendSyncAfterTunnel(scope, context)

    fun ensureDataSyncAfterTunnel(scope: CoroutineScope, context: Context) =
        ensureBackendSyncAfterTunnel(scope, context)

    private suspend fun waitForTunnel(scope: CoroutineScope): Boolean {
        val deadline = System.currentTimeMillis() + TUNNEL_WAIT_MS
        while (System.currentTimeMillis() < deadline && scope.isActive) {
            if (!WdttTunnelManager.running.value) return false
            if (WdttTunnelManager.tunnelReady.value) return true
            delay(500)
        }
        return WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value
    }

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
        syncJob?.cancel()
        syncJob = null
        VpnSessionState.resetBackendSync()
    }

    /** ДО stopAndAwait — тот же tunnel path, что connect. */
    suspend fun notifyDisconnect(context: Context) {
        if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) {
            DebugLog.w(TAG, "disconnect skipped — tunnel not up")
            return
        }
        val ok = runCatching { repo(context).notifyDisconnectBeforeTunnelStop() }.getOrDefault(false)
        if (ok) DebugLog.i(TAG, "before stop: disconnect OK") else DebugLog.w(TAG, "before stop: disconnect FAILED")
    }
}
