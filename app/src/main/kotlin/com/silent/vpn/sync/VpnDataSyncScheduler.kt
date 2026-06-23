package com.silent.vpn.sync

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat
import com.silent.vpn.vpn.WdttTunnelManager

/** Запуск/остановка фоновой синхронизации при основном VPN. */
object VpnDataSyncScheduler {
    fun onMainVpnConnected(context: Context) {
        if (WdttTunnelManager.isBootstrapMode()) return
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
}
