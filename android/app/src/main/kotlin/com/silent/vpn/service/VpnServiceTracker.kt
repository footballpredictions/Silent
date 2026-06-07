package com.silent.vpn.service

import android.app.ActivityManager
import android.content.ComponentName
import android.content.Context
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.WdttTunnelManager

/** Проверка, жив ли foreground VPN-сервис (не полагаться на static после kill процесса). */
object VpnServiceTracker {
    private const val TAG = "VpnServiceTracker"

    fun isServiceAlive(context: Context): Boolean {
        val am = context.getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        val cn = ComponentName(context.applicationContext, SilentVpnService::class.java)
        @Suppress("DEPRECATION")
        return am.getRunningServices(Int.MAX_VALUE).any { svc ->
            svc.service == cn || svc.service.className == cn.className
        }
    }

    /** Сброс «залипшего» ACTIVE на плитке, если процесс убит, а флаги остались. */
    fun reconcileStaleSession(context: Context): Boolean {
        if (isServiceAlive(context)) return true
        val stale = SilentVpnService.isRunning ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.tunnelReady.value
        if (!stale) return false
        DebugLog.w(TAG, "VPN service not running — clear stale session flags")
        SilentVpnService.resetStaleSession()
        WdttTunnelManager.clearStaleSession()
        VpnBackendSync.stop()
        VpnSessionState.resetBackendSync()
        VpnTileHelper.requestUpdate(context.applicationContext)
        return false
    }
}
