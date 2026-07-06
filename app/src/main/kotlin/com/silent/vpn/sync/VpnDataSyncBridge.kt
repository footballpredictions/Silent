package com.silent.vpn.sync

import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.data.ConfigSyncCoordinator

/** UI (MainViewModel) регистрирует listener; VpnDataSyncService дергает tick через него. */
object VpnDataSyncBridge {
    @Volatile
    var configSyncListener: ConfigSyncCoordinator.Listener? = null

    @Volatile
    var onCycleCompleted: (() -> Unit)? = null

    /** OTA-проверка внутри той же overlay-сессии, что initial sync (LTE). */
    @Volatile
    var onOtaCheckInOverlaySession: (suspend () -> Unit)? = null
}
