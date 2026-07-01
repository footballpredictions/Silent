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
        private const val INITIAL_DELAY_MS = 400L
        private const val INITIAL_DELAY_MOBILE_MS = 150L
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
            val repo = repository()
            val delayMs = if (SilentRepository.APP_EXCLUDED_FROM_VPN && repo.isOnMobileData()) {
                INITIAL_DELAY_MOBILE_MS
            } else {
                INITIAL_DELAY_MS
            }
            delay(delayMs)

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
            !WdttTunnelManager.isBootstrapMode() &&
            WdttTunnelManager.activeWorkers.value >= 1 &&
            !WdttTunnelManager.isWorkerRampUpActive()

    /** Для LTE overlay-sync достаточно tunnelReady — воркеры добираются в ramp-up. */
    private fun canSyncOverlay(): Boolean =
        SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            !WdttTunnelManager.isBootstrapMode()

    private suspend fun waitUntilSyncReady() {
        val repo = repository()
        val overlayPath = SilentRepository.APP_EXCLUDED_FROM_VPN && repo.isOnMobileData()
        val deadline = System.currentTimeMillis() + if (overlayPath) 45_000L else 90_000L
        while (System.currentTimeMillis() < deadline) {
            if (if (overlayPath) canSyncOverlay() else canSync()) return
            if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) return
            delay(300)
        }
    }

    /** Один полный sync за VPN-сессию; retry — внутри той же overlay-сессии на LTE. */
    private suspend fun runInitialFullSync() {
        waitUntilSyncReady()
        val repo = repository()
        val overlayPath = SilentRepository.APP_EXCLUDED_FROM_VPN && repo.isOnMobileData()
        if (!(if (overlayPath) canSyncOverlay() else canSync())) return
        if (!repo.isLoggedIn()) return

        VpnDataSyncState.setSyncing()
        updateNotification("Синхронизация данных…")
        MobileSyncLog.i("syncService", "initial sync start mobile=${repo.isOnMobileData()}")

        if (overlayPath) VpnSessionState.initialOverlaySyncActive = true
        val ok = performFullSync(repo)

        if (ok) {
            VpnSessionState.tunnelDataSyncCompleted = true
            VpnSessionState.backendSyncCompleted = true
            VpnSessionState.tunnelDataSyncFinishedAtMs = System.currentTimeMillis()
            VpnDataSyncState.setOk()
            updateNotification("Данные актуальны")
            VpnDataSyncBridge.onCycleCompleted?.invoke()
            MobileSyncLog.i("syncService", "initial sync OK")
        } else {
            VpnDataSyncState.setError("Не удалось синхронизировать данные")
            updateNotification("Ошибка синхронизации")
            MobileSyncLog.w("syncService", "initial sync FAILED")
        }
        if (overlayPath) VpnSessionState.initialOverlaySyncActive = false

        delay(2_000)
        if (canSync()) {
            updateNotification("Синхронизация в фоне")
        }
    }

    private suspend fun performFullSync(repo: SilentRepository): Boolean {
        val syncBody: suspend () -> Boolean = {
            runCatching {
                repo.setTunnelApiFromWgAddress(WdttTunnelManager.lastWgAddress())
                if (repo.isOnMobileData()) {
                    com.silent.vpn.vpn.TunnelApiProxy.stopAndAwait()
                }
                repo.prepareMainVpnDirectApi()
                MobileSyncLog.i("syncService", "sync API url=${repo.getServerUrl()}")
                var ok = repo.syncAllViaTunnel()
                if (ok) {
                    repo.seedSyncRevisionsAfterTunnelSync()
                } else if (canSyncOverlay()) {
                    MobileSyncLog.w("syncService", "sync retry inside overlay")
                    delay(INITIAL_RETRY_MS)
                    ok = repo.syncAllViaTunnel()
                    if (ok) repo.seedSyncRevisionsAfterTunnelSync()
                }
                ok
            }.getOrElse { e ->
                MobileSyncLog.e("syncService", "initial sync failed", e)
                false
            }
        }
        return withTimeoutOrNull(120_000L) {
            if (SilentRepository.APP_EXCLUDED_FROM_VPN && repo.isOnMobileData()) {
                MobileSyncLog.i("syncService", "overlay session start (LTE initial sync)")
                com.silent.vpn.vpn.WdttTunnelManager.withApiOverlayBrief(
                    block = syncBody,
                    allowDuringRampUp = true,
                    skipIntervalThrottle = true,
                )
            } else {
                syncBody()
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
