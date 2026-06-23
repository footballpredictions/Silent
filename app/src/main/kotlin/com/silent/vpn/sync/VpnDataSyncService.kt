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
import com.silent.vpn.data.ConfigSyncCoordinator
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
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Foreground sync по активному основному VPN — без WG overlay.
 * HTTP через tunnel API direct (app в WG) или proxy (bootstrap legacy).
 */
class VpnDataSyncService : Service() {
    companion object {
        private const val TAG = "UpdateService"
        const val ACTION_START = "com.silent.vpn.sync.START"
        const val ACTION_STOP = "com.silent.vpn.sync.STOP"
        private const val CHANNEL_ID = "silent_data_sync"
        private const val NOTIF_ID = 42
        private const val POLL_MS = 30 * 60 * 1000L
        private const val INITIAL_DELAY_MS = 3_000L
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
            while (isActive && canSync()) {
                runSyncCycle()
                delay(POLL_MS)
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

    private suspend fun runSyncCycle() {
        if (!canSync()) return
        val repo = repository()
        if (!repo.isLoggedIn()) return

        VpnDataSyncState.setSyncing()
        updateNotification("Синхронизация данных…")
        Log.i(TAG, "sync cycle start")

        val ok = withTimeoutOrNull(120_000L) {
            runCatching {
                repo.setTunnelApiFromWgAddress(WdttTunnelManager.lastWgAddress())
                if (SilentRepository.APP_EXCLUDED_FROM_VPN) {
                    if (!repo.ensureTunnelApiProxy()) {
                        Log.w(TAG, "tunnel proxy not ready")
                    }
                } else {
                    repo.prepareMainVpnDirectApi()
                }
                if (!VpnSessionState.tunnelDataSyncCompleted) {
                    val initial = repo.syncAllViaTunnel()
                    if (initial) {
                        VpnSessionState.tunnelDataSyncCompleted = true
                        VpnSessionState.backendSyncCompleted = true
                        Log.i(TAG, "initial syncAllViaTunnel OK")
                    }
                }
                val listener = VpnDataSyncBridge.configSyncListener
                if (listener != null && listener.isPollAllowed()) {
                    ConfigSyncCoordinator.tickNow(repo, applicationContext, listener)
                }
                VpnDataSyncBridge.onCycleCompleted?.invoke()
                true
            }.getOrElse { e ->
                Log.e(TAG, "sync cycle failed", e)
                false
            }
        } ?: false

        if (ok) {
            VpnDataSyncState.setOk()
            updateNotification("Данные актуальны")
            Log.i(TAG, "sync cycle OK")
        } else {
            VpnDataSyncState.setError("Не удалось синхронизировать данные")
            updateNotification("Ошибка синхронизации")
            Log.w(TAG, "sync cycle FAILED")
        }
        delay(2_000)
        if (canSync()) {
            updateNotification("Синхронизация в фоне")
        }
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
                "Синхронизация Silent VPN",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Обновление подписки, хешей и темы через VPN"
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
