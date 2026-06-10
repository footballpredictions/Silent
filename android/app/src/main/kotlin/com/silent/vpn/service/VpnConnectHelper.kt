package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardHelper
import kotlinx.coroutines.runBlocking

/** Чистый старт VPN — после kill процесса с включённым VPN / залипшей плитки. */
object VpnConnectHelper {
    private const val TAG = "VpnConnectHelper"

    /** Полная очистка libclient + WG перед новым CONNECT. */
    fun ensureCleanSlate(context: Context) {
        SessionTrace.mark("VpnConnectHelper.ensureCleanSlate")
        val appCtx = context.applicationContext
        runBlocking {
            runCatching { WdttTunnelManager.stopAndAwait() }
                .onFailure { e -> DebugLog.w(TAG, "stopAndAwait: ${e.message}") }
            runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                .onFailure { e -> DebugLog.w(TAG, "forceStopSilentTunnel: ${e.message}") }
        }
        WdttTunnelManager.clearStaleSession()
        SilentVpnService.resetStaleSession()
        VpnBackendSync.stop()
        VpnSessionState.resetBackendSync()
        VpnServiceTracker.markSessionActive(appCtx, false)
        VpnTileHelper.requestUpdate(appCtx)
    }
}
