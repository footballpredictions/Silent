package com.silent.vpn.service

import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

/**
 * Единое состояние VPN-сессии — как [TunnelManager.running] в proxy-turn-vk-android.
 */
object VpnSessionState {

    @Volatile
    var backendSyncCompleted: Boolean = false

    /** Хеши/конfig из VpnBackendSync (сервис) или MainViewModel. */
    @Volatile
    var tunnelDataSyncCompleted: Boolean = false

    /** Туннель реально работает: WG + живой libclient + ≥1 воркер. */
    fun isActive(): Boolean =
        SilentVpnService.isRunning &&
            WdttTunnelManager.running.value &&
            WdttTunnelManager.isTransportHealthy()

    /** Идёт подключение или капча. */
    fun isBusy(): Boolean =
        isCaptchaPending() ||
            (SilentVpnService.isRunning &&
                WdttTunnelManager.running.value &&
                !WdttTunnelManager.tunnelReady.value)

    fun isCaptchaPending(): Boolean =
        WdttTunnelManager.isCaptchaInProgress() || ManlCaptchaWebViewManager.isCaptchaPending

    fun resetBackendSync() {
        backendSyncCompleted = false
        tunnelDataSyncCompleted = false
    }
}
