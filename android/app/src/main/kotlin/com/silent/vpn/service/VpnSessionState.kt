package com.silent.vpn.service

import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

/** Единое состояние VPN-сессии (плитка QS и приложение — один туннель). Только чтение, без side-effects. */
object VpnSessionState {

    @Volatile
    var backendSyncCompleted: Boolean = false

    private fun tunnelUp(): Boolean =
        WdttTunnelManager.tunnelReady.value && WdttTunnelManager.activeWorkers.value >= 1

    /** Туннель поднят и libclient готов. */
    fun isActive(): Boolean {
        val result = SilentVpnService.isRunning && tunnelUp()
        SessionTrace.mark(
            "VpnSessionState.isActive",
            "=$result running=${SilentVpnService.isRunning} tunnel=${tunnelUp()} workers=${WdttTunnelManager.activeWorkers.value}",
        )
        return result
    }

    /** Connect / ramp-up / капча — нельзя перезапускать второй connect. */
    fun isBusy(): Boolean {
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

    /** Можно отменить с плитки: подключено или идёт connect/ramp-up. */
    fun canDisconnectFromTile(): Boolean = isActive() || isBusy()

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
