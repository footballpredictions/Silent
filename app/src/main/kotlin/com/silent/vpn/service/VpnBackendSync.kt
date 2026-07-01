package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Backend через VPN-туннель:
 * - Initial sync — [com.silent.vpn.sync.VpnDataSyncService] (один раз за сессию)
 * - ДО stop VPN: POST /disconnect (tunnel path, с таймаутом)
 */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"
    private const val DISCONNECT_NOTIFY_TIMEOUT_MS = 1_500L

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
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
