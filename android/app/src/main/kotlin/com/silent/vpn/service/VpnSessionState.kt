package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.util.SessionTrace
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
        context?.let {
            val serviceAlive = VpnServiceTracker.reconcileStaleSession(it)
            if (!serviceAlive) {
                SessionTrace.mark("VpnSessionState.isActive", "false (no service)")
                return false
            }
        }
        val result = SilentVpnService.isRunning && tunnelUp()
        SessionTrace.mark(
            "VpnSessionState.isActive",
            "=$result running=${SilentVpnService.isRunning} tunnel=${tunnelUp()} workers=${WdttTunnelManager.activeWorkers.value}",
        )
        return result
    }

    /** Connect / ramp-up / капча — нельзя перезапускать. */
    fun isBusy(context: Context? = null): Boolean {
        context?.let {
            val serviceAlive = VpnServiceTracker.reconcileStaleSession(it)
            if (!serviceAlive) {
                val busy = SilentVpnService.isRunning ||
                    WdttTunnelManager.running.value ||
                    isCaptchaPending()
                SessionTrace.mark("VpnSessionState.isBusy", "=$busy (no service)")
                return busy
            }
        }
        val result = SilentVpnService.isRunning ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending
        SessionTrace.mark(
            "VpnSessionState.isBusy",
            "=$result running=${SilentVpnService.isRunning} wdtt=${WdttTunnelManager.running.value}",
        )
        return result
    }

    fun isCaptchaPending(): Boolean {
        val result = WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending
        SessionTrace.mark("VpnSessionState.isCaptchaPending", "=$result")
        return result
    }

    fun resetBackendSync() {
        SessionTrace.mark("VpnSessionState.resetBackendSync")
        backendSyncCompleted = false
    }
}
