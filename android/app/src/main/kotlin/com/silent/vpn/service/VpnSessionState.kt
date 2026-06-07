package com.silent.vpn.service

import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

/** Единое состояние VPN-сессии (плитка QS и приложение — один туннель). */
object VpnSessionState {

    @Volatile
    var backendSyncCompleted: Boolean = false

    /** Туннель поднят и libclient готов. */
    fun isActive(): Boolean =
        SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.activeWorkers.value >= 1

    /** Connect / ramp-up / капча — нельзя перезапускать. */
    fun isBusy(): Boolean =
        SilentVpnService.isRunning ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending

    fun isCaptchaPending(): Boolean =
        WdttTunnelManager.isCaptchaInProgress() ||
            ManlCaptchaWebViewManager.isCaptchaPending

    fun resetBackendSync() {
        backendSyncCompleted = false
    }
}
