package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.CoroutineScope

/**
 * Онлайн-статус устройства теперь ведёт wdtt-server (server-to-server репорт в backend:
 * см. reportDeviceOnline в server.go). Поэтому клиент НЕ делает online-heartbeat через
 * WG-overlay во время сессии — туннель поднимается один раз, без переключений.
 *
 * Объект сохранён ради совместимости с вызывающим кодом (сервис/плитка/MainViewModel).
 */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    /** Больше не делает heartbeat: online ставит wdtt-server при подъёме WG. */
    fun ensureRunning(scope: CoroutineScope, context: Context) {
        VpnSessionState.backendSyncCompleted = true
    }

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
        VpnSessionState.resetBackendSync()
    }

    /**
     * Best-effort снятие «онлайн» при выключении VPN. Без WG-overlay: туннель уже гасится.
     * Если backend недоступен напрямую (заблокирован у пользователя) — статус снимет
     * wdtt-server по обрыву соединения + backend по таймауту неактивности.
     */
    suspend fun notifyDisconnect(context: Context) {
        val r = repo(context)
        if (!r.isLoggedIn()) return
        runCatching {
            r.getApi().disconnect(DisconnectRequest(r.getDeviceFingerprint()))
        }.onFailure { e ->
            DebugLog.w(TAG, "disconnect API skipped (online снимет wdtt-server): ${e.message}")
        }
    }
}
