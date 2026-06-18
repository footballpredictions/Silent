package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import java.util.concurrent.atomic.AtomicBoolean

/** Синхронизация VPN-сессии с системой и плиткой QS. */
object VpnServiceTracker {
    private const val TAG = "VpnServiceTracker"
    private const val PREF_VPN_SESSION_ACTIVE = "vpn_session_active"
    /** Не дёргать reconcile чаще — иначе шторм с QS onStartListening. */
    private const val MIN_RECONCILE_INTERVAL_MS = 5_000L

    private val reconciling = AtomicBoolean(false)

    @Volatile
    private var lastReconcileMs = 0L

    fun isSessionMarkedActive(context: Context): Boolean =
        SilentPrefs.open(context.applicationContext).getBoolean(PREF_VPN_SESSION_ACTIVE, false)

    fun markSessionActive(context: Context, active: Boolean) {
        SessionTrace.mark("VpnServiceTracker.markSessionActive", "active=$active")
        SilentPrefs.open(context.applicationContext).edit()
            .putBoolean(PREF_VPN_SESSION_ACTIVE, active)
            .commit()
    }

    /**
     * Сброс залипшего pref/флагов если сервис мёртв (в т.ч. из плитки при открытии шторки).
     */
    fun reconcileStaleSession(context: Context): Boolean {
        if (SilentVpnService.isRunning || WdttTunnelManager.running.value) {
            return true
        }
        val now = System.currentTimeMillis()
        if (now - lastReconcileMs < MIN_RECONCILE_INTERVAL_MS) {
            return false
        }
        if (!reconciling.compareAndSet(false, true)) {
            return false
        }
        lastReconcileMs = now
        SessionTrace.enter("VpnServiceTracker.reconcileStaleSession")
        val appCtx = context.applicationContext
        try {
            val hadStale =
                isSessionMarkedActive(appCtx) ||
                    WdttTunnelManager.running.value ||
                    WdttTunnelManager.tunnelReady.value

            if (hadStale) {
                DebugLog.w(TAG, "Dead process / stale VPN flags — reset")
                markSessionActive(appCtx, false)
                SilentVpnService.resetStaleSession()
                WdttTunnelManager.clearStaleSession()
                VpnBackendSync.stop()
                VpnSessionState.resetBackendSync()
                VpnConnectHelper.noteCleanSlate()
                VpnTileHelper.requestUpdate(appCtx)
            }
            SessionTrace.exit("VpnServiceTracker.reconcileStaleSession", if (hadStale) "cleared" else "idle")
            return hadStale
        } finally {
            reconciling.set(false)
        }
    }
}
