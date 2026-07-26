package com.silent.vpn.service

import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

/**
 * Единое состояние VPN-сессии — как [TunnelManager.running] в proxy-turn-vk-android.
 * Учитывает и WDTT, и debug-olcrtc (плитка / UI).
 */
object VpnSessionState {

    @Volatile
    var backendSyncCompleted: Boolean = false

    /** Хеши/конfig из VpnBackendSync (сервис) или MainViewModel. */
    @Volatile
    var tunnelDataSyncCompleted: Boolean = false

    @Volatile
    var tunnelDataSyncFinishedAtMs: Long = 0L

    /** Идёт единственный overlay initial sync — другие overlay не стартуют. */
    @Volatile
    var initialOverlaySyncActive: Boolean = false

    /** Туннель работает: WDTT (WG+libclient) или olcrtc (SOCKS+hev). */
    fun isActive(): Boolean {
        if (OlcrtcTunnelManager.tunnelReady.value) return true
        return SilentVpnService.isRunning &&
            WdttTunnelManager.running.value &&
            WdttTunnelManager.isTransportReadyStrict()
    }

    /** Идёт подключение или капча. */
    fun isBusy(): Boolean =
        isCaptchaPending() ||
            (OlcrtcTunnelManager.running.value && !OlcrtcTunnelManager.tunnelReady.value) ||
            (SilentVpnService.isRunning &&
                WdttTunnelManager.running.value &&
                !WdttTunnelManager.tunnelReady.value)

    fun isCaptchaPending(): Boolean =
        WdttTunnelManager.isCaptchaInProgress() || ManlCaptchaWebViewManager.isCaptchaPending

    fun resetBackendSync() {
        backendSyncCompleted = false
        tunnelDataSyncCompleted = false
        tunnelDataSyncFinishedAtMs = 0L
        initialOverlaySyncActive = false
    }
}
