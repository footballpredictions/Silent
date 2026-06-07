package com.silent.vpn.service

import android.app.ActivityManager
import android.content.ComponentName
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
    private val reconciling = AtomicBoolean(false)

    fun isSessionMarkedActive(context: Context): Boolean =
        SilentPrefs.open(context.applicationContext).getBoolean(PREF_VPN_SESSION_ACTIVE, false)

    fun markSessionActive(context: Context, active: Boolean) {
        SessionTrace.mark("VpnServiceTracker.markSessionActive", "active=$active")
        SilentPrefs.open(context.applicationContext).edit()
            .putBoolean(PREF_VPN_SESSION_ACTIVE, active)
            .commit()
    }

    fun isServiceAlive(context: Context): Boolean {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val cn = ComponentName(context.applicationContext, SilentVpnService::class.java)
        @Suppress("DEPRECATION")
        val alive = am.getRunningServices(Int.MAX_VALUE).any { svc ->
            svc.service == cn || svc.service.className == cn.className
        }
        SessionTrace.mark("VpnServiceTracker.isServiceAlive", "alive=$alive")
        return alive
    }

    /**
     * Сброс «залипшего» состояния, если сервис мёртв или память не совпадает с системой.
     * @return true если VPN-сервис реально запущен в системе
     */
    fun reconcileStaleSession(context: Context): Boolean {
        if (!reconciling.compareAndSet(false, true)) {
            return isServiceAlive(context.applicationContext)
        }
        SessionTrace.enter("VpnServiceTracker.reconcileStaleSession")
        val appCtx = context.applicationContext
        try {
            if (isServiceAlive(appCtx)) {
                if (VpnSessionState.isActive()) {
                    markSessionActive(appCtx, true)
                }
                SessionTrace.exit("VpnServiceTracker.reconcileStaleSession", "service alive")
                return true
            }

            val staleMemory = SilentVpnService.isRunning ||
                WdttTunnelManager.running.value ||
                WdttTunnelManager.tunnelReady.value
            val stalePref = isSessionMarkedActive(appCtx)

            if (!staleMemory && !stalePref) {
                SessionTrace.exit("VpnServiceTracker.reconcileStaleSession", "idle ok")
                return false
            }

            DebugLog.w(TAG, "VPN service not running — clear stale session (mem=$staleMemory pref=$stalePref)")
            SessionTrace.warn("VpnServiceTracker.reconcileStaleSession", "clear stale mem=$staleMemory pref=$stalePref")
            markSessionActive(appCtx, false)
            SilentVpnService.resetStaleSession()
            WdttTunnelManager.clearStaleSession()
            VpnBackendSync.stop()
            VpnSessionState.resetBackendSync()
            VpnTileHelper.requestUpdate(appCtx)
            SessionTrace.exit("VpnServiceTracker.reconcileStaleSession", "cleared stale")
            return false
        } finally {
            reconciling.set(false)
        }
    }
}
