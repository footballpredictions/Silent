package com.silent.vpn.sync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.silent.vpn.MainActivity
import com.silent.vpn.R
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Foreground sync по активному основному VPN.
 * Один полный sync за VPN-сессию; затем «Синхронизация в фоне» без повторов.
 */
class VpnDataSyncService : Service() {
    companion object {
        private const val TAG = "UpdateService"
        const val ACTION_START = "com.silent.vpn.sync.START"
        const val ACTION_STOP = "com.silent.vpn.sync.STOP"
        private const val CHANNEL_ID = "silent_vpn_status_v2"
        private const val NOTIF_ID = 1001
        private const val INITIAL_RETRY_MS = 8_000L
        private const val INITIAL_DELAY_MS = 2_000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loopJob: Job? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopLoop()
                VpnDataSyncState.setIdle()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                if (!SilentVpnService.isRunning || WdttTunnelManager.isBootstrapMode()) {
                    stopSelf()
                    return START_NOT_STICKY
                }
                startForeground(NOTIF_ID, buildNotification("Синхронизация данных…"))
                startLoop()
                return START_STICKY
            }
        }
    }

    override fun onDestroy() {
        stopLoop()
        scope.cancel()
        super.onDestroy()
    }

    private fun startLoop() {
        if (loopJob?.isActive == true) return
        loopJob = scope.launch {
            delay(INITIAL_DELAY_MS)

            if (!VpnSessionState.tunnelDataSyncCompleted) {
                runInitialFullSync()
            } else {
                VpnDataSyncState.setOk()
                updateNotification("Синхронизация в фоне")
                delay(2_000)
            }

            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun stopLoop() {
        loopJob?.cancel()
        loopJob = null
    }

    private fun canSync(): Boolean =
        SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            !WdttTunnelManager.isBootstrapMode()

    /** Один полный sync за VPN-сессию (+ один retry при ошибке). */
    private suspend fun runInitialFullSync() {
        if (!canSync()) return
        val repo = repository()
        if (!repo.isLoggedIn()) return

        VpnDataSyncState.setSyncing()
        updateNotification("Синхронизация данных…")
        Log.i(TAG, "initial sync start")

        var ok = performFullSync(repo)
        if (!ok && canSync()) {
            Log.w(TAG, "initial sync retry in ${INITIAL_RETRY_MS}ms")
            delay(INITIAL_RETRY_MS)
            ok = performFullSync(repo)
        }

        if (ok) {
            VpnSessionState.tunnelDataSyncCompleted = true
            VpnSessionState.backendSyncCompleted = true
            VpnDataSyncState.setOk()
            updateNotification("Данные актуальны")
            VpnDataSyncBridge.onCycleCompleted?.invoke()
            Log.i(TAG, "initial sync OK")
        } else {
            VpnDataSyncState.setError("Не удалось синхронизировать данные")
            updateNotification("Ошибка синхронизации")
            Log.w(TAG, "initial sync FAILED")
        }

        delay(2_000)
        if (canSync()) {
            updateNotification("Синхронизация в фоне")
        }
    }

    private suspend fun performFullSync(repo: SilentRepository): Boolean {
        return withTimeoutOrNull(120_000L) {
            runCatching {
                repo.setTunnelApiFromWgAddress(WdttTunnelManager.lastWgAddress())
                if (SilentRepository.APP_EXCLUDED_FROM_VPN) {
                    if (!repo.ensureTunnelApiProxy()) {
                        Log.w(TAG, "tunnel proxy not ready")
                    }
                } else {
                    repo.prepareMainVpnDirectApi()
                }
                repo.syncAllViaTunnel()
            }.getOrElse { e ->
                Log.e(TAG, "initial sync failed", e)
                false
            }
        } ?: false
    }

    private fun repository(): SilentRepository =
        EntryPointAccessors.fromApplication(applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    private fun createChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                "Silent VPN",
                NotificationManager.IMPORTANCE_DEFAULT,
            ).apply {
                description = "Статус VPN и синхронизация данных"
                setShowBadge(false)
            },
        )
    }

    private fun buildNotification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_tile_silent)
            .setContentTitle("Silent VPN")
            .setContentText(text)
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(NOTIF_ID, buildNotification(text))
    }
}
