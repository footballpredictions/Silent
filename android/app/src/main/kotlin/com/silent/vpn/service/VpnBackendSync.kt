package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.CoroutineScope

/**
 * Онлайн-статус устройства ведёт wdtt-server (s2s → backend).
 * Клиент при выключении VPN только снимает «онлайн» через POST /disconnect,
 * пока туннель ещё поднят (через WG-overlay на заблокированных сетях).
 */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun ensureRunning(scope: CoroutineScope, context: Context) {
        VpnSessionState.backendSyncCompleted = true
    }

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
        VpnSessionState.resetBackendSync()
    }

    /**
     * Снять «онлайн» на backend **до** остановки libclient/WG.
     * На мобильном интернете (блокировка) публичный API недоступен — запрос идёт
     * через краткий overlay к 10.66.66.1, пока VPN ещё активен.
     */
    suspend fun notifyDisconnect(context: Context) {
        val r = repo(context)
        if (!r.isLoggedIn()) return
        WdttTunnelManager.prepareForShutdown()
        runCatching {
            when {
                SilentVpnService.isRunning &&
                    WdttTunnelManager.tunnelReady.value &&
                    r.needsTunnelApiOverlay() -> {
                    r.withTunnelApiWhenExcluded { postDisconnect(r) }
                }
                SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value -> {
                    r.setTunnelApiFromWgAddress(WdttTunnelManager.lastWgAddress())
                    postDisconnect(r)
                }
                else -> postDisconnect(r)
            }
        }.onFailure { e ->
            DebugLog.w(TAG, "disconnect API failed: ${e.message}")
        }
    }

    private suspend fun postDisconnect(r: SilentRepository) {
        val res = r.getApi().disconnect(DisconnectRequest(r.getDeviceFingerprint()))
        if (res.isSuccessful) {
            DebugLog.i(TAG, "disconnect API OK — online cleared before tunnel stop")
        } else {
            DebugLog.w(TAG, "disconnect API HTTP ${res.code()}")
        }
    }
}
