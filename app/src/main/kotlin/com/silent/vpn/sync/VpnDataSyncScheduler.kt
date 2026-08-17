package com.silent.vpn.sync

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.policy.ConfigSyncSkipPolicy
import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors

/** Запуск/остановка фоновой синхронизации при основном VPN. */
object VpnDataSyncScheduler {
    fun onMainVpnConnected(context: Context) {
        if (WdttTunnelManager.isBootstrapMode()) return
        val repo = repository(context)
        if (
            ConfigSyncSkipPolicy.lteUsesInBandConfigSync(
                onMobileData = repo.isOnMobileData(),
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
            )
        ) {
            completeFromClientSync(repo)
            return
        }
        val intent = Intent(context, VpnDataSyncService::class.java).apply {
            action = VpnDataSyncService.ACTION_START
        }
        ContextCompat.startForegroundService(context, intent)
    }

    fun onMainVpnDisconnected(context: Context) {
        val intent = Intent(context, VpnDataSyncService::class.java).apply {
            action = VpnDataSyncService.ACTION_STOP
        }
        context.startService(intent)
    }

    /** Snapshot с /vpn/config уже в кеше; online — wdtt /internal/online по GETCONF. */
    internal fun completeFromClientSync(repo: SilentRepository): Boolean {
        val applied = repo.applyCachedClientSync()
        VpnSessionState.tunnelDataSyncCompleted = true
        VpnSessionState.backendSyncCompleted = true
        VpnSessionState.tunnelDataSyncFinishedAtMs = System.currentTimeMillis()
        VpnDataSyncState.setOk()
        MobileSyncLog.i(
            "syncService",
            "LTE in-band: skip HTTP/overlay, client_sync applied=$applied",
        )
        return applied
    }

    private fun repository(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(
            context.applicationContext,
            AppEntryPoint::class.java,
        ).silentRepository()
}
