package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

/** Единое состояние VPN-сессии (плитка QS и приложение — один туннель). */
object VpnSessionState {

    @Volatile
    var backendSyncCompleted: Boolean = false

    private fun tunnelUp(): Boolean =
        WdttTunnelManager.tunnelReady.value && WdttTunnelManager.activeWorkers.value >= 1

    /** Туннель поднят и libclient готов; сервис реально запущен в системе. */
    fun isActive(context: Context? = null): Boolean {
        context?.let { if (!VpnServiceTracker.reconcileStaleSession(it)) return false }
        return SilentVpnService.isRunning && tunnelUp()
    }

    /** Connect / ramp-up / капча — нельзя перезапускать. */
    fun isBusy(context: Context? = null): Boolean {
        context?.let { if (!VpnServiceTracker.reconcileStaleSession(it)) return false }
        return SilentVpnService.isRunning ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending
    }

    fun isCaptchaPending(): Boolean =
        WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending

    fun resetBackendSync() {
        backendSyncCompleted = false
    }
}
