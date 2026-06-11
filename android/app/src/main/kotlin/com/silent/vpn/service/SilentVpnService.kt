package com.silent.vpn.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import com.silent.vpn.MainActivity
import com.silent.vpn.R
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vk.HashParser
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardConfigBuilder
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import dagger.hilt.android.EntryPointAccessors
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.silent.vpn.data.HashItemDto
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * Foreground VPN service — сеть/LTE как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * WakeLock, WifiLock, NetworkCallback (NOT_VPN), pause/resume и restartTransport при смене Wi‑Fi ↔ LTE.
 */
class SilentVpnService : Service() {

    companion object {
        private const val CHANNEL_ID = "silent_vpn"
        private const val NOTIF_ID = 1001
        /** Не перезапускать libclient при смене сети в первые 2 мин после connect. */
        private const val NETWORK_GRACE_MS = 120_000L
        private const val NETWORK_CHANGE_DEBOUNCE_MS = 90_000L
        private const val NOTIF_UPDATE_MIN_MS = 3_000L
        const val ACTION_CONNECT = "com.silent.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.silent.vpn.DISCONNECT"
        /** Другой VPN подключился — Android отозвал наш VpnService. */
        const val ACTION_EXTERNAL_REVOKED = "com.silent.vpn.EXTERNAL_REVOKED"
        const val EXTRA_CONFIG = "vpn_config_json"
        const val EXTRA_IS_BOOTSTRAP = "is_bootstrap"
        var isRunning = false
            private set

        fun resetStaleSession() {
            SessionTrace.mark("SilentVpnService.resetStaleSession")
            isRunning = false
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var lastNetworkChangeTime = 0L
    private var connectStartedAtMs = 0L
    private val activeNetworks = mutableSetOf<Network>()
    private var isTunnelPaused = false
    private var transportWatchdogJob: Job? = null
    private var statsUpdaterJob: Job? = null
    @Volatile
    private var backendSyncTriggered = false
    private var performanceLocksHeld = false
    private var lastNotifUpdateMs = 0L
    private var lastNotifBody = ""
    private var vpnOwnerCallback: ConnectivityManager.NetworkCallback? = null

    override fun onCreate() {
        super.onCreate()
        SessionTrace.mark("SilentVpnService.onCreate")
        createNotificationChannel()
        // Kill с включённым VPN: pref=true, isRunning=false — сразу чистим, до START_STICKY restore.
        if (!isRunning && VpnServiceTracker.isSessionMarkedActive(this)) {
            VpnConnectHelper.ensureCleanSlate(this)
        }
    }

    /** Как в proxy-turn-vk-android: отдельный цикл обновления уведомления (переживает reconnect). */
    private fun startStatsUpdater() {
        statsUpdaterJob?.cancel()
        statsUpdaterJob = scope.launch {
            SessionTrace.enter("SilentVpnService.statsUpdater")
            delay(300)
            while (isActive) {
                if (!WdttTunnelManager.running.value && !isTunnelPaused) {
                    if (!isRunning) {
                        stopSelf()
                        break
                    }
                }
                if (isRunning) {
                    val stats = WdttTunnelManager.stats.value
                    if (WdttTunnelManager.tunnelReady.value) {
                        releasePerformanceLocks()
                        if (!VpnServiceTracker.isSessionMarkedActive(this@SilentVpnService)) {
                            VpnServiceTracker.markSessionActive(this@SilentVpnService, true)
                        }
                        postVpnNotification(stats)
                        if (
                            !backendSyncTriggered &&
                            VpnSessionState.isActive() &&
                            !VpnSessionState.tunnelDataSyncCompleted
                        ) {
                            backendSyncTriggered = true
                            VpnBackendSync.ensureBackendSyncAfterTunnel(scope, this@SilentVpnService)
                        }
                    } else if (WdttTunnelManager.running.value) {
                        startFg(buildConnectingNotification())
                    }
                }
                delay(2000)
            }
            SessionTrace.exit("SilentVpnService.statsUpdater")
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        SessionTrace.mark("SilentVpnService.onStartCommand", "action=${intent?.action}")
        when (intent?.action) {
            ACTION_CONNECT -> {
                val configJson = intent.getStringExtra(EXTRA_CONFIG)
                if (configJson == null) {
                    SessionTrace.warn("SilentVpnService.CONNECT", "no config")
                    DebugLog.e("VpnService", "CONNECT without config")
                    stopSelf()
                    return START_NOT_STICKY
                }
                if (VpnTileConnect.isCaptchaPending()) {
                    SessionTrace.mark("SilentVpnService.CONNECT", "blocked captcha")
                    DebugLog.w("VpnService", "CONNECT ignored — VK captcha in progress")
                    ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
                    return START_STICKY
                }
        if (WdttTunnelManager.running.value && isRunning && WdttTunnelManager.tunnelReady.value) {
            SessionTrace.mark("SilentVpnService.CONNECT", "already running")
            VpnTileHelper.requestUpdate(this)
            return START_STICKY
        }
                VpnConnectHelper.prepareForConnect(this)
                SessionTrace.enter(
                    "SilentVpnService.CONNECT",
                    "device=${runCatching { JSONObject(configJson).optString("device_id") }.getOrNull()?.take(8)}",
                )
                connectStartedAtMs = System.currentTimeMillis()
                lastNetworkChangeTime = 0L
                lastNotifBody = ""
                lastNotifUpdateMs = 0L
                backendSyncTriggered = false
                setupNetworkCallback()
                startTransportWatchdog()
                startStatsUpdater()
                acquirePerformanceLocks()
                startFg(buildConnectingNotification())
                setupVpnOwnershipMonitor()
                connect(configJson, intent.getBooleanExtra(EXTRA_IS_BOOTSTRAP, false))
                VpnTileHelper.requestUpdate(this)
            }
            ACTION_DISCONNECT -> {
                SessionTrace.enter("SilentVpnService.DISCONNECT")
                disconnect()
            }
            ACTION_EXTERNAL_REVOKED -> {
                SessionTrace.warn("SilentVpnService", "EXTERNAL_REVOKED")
                if (isRunning) {
                    DebugLog.w("VpnService", "DISCONNECT — VPN revoked by another app")
                    disconnect()
                }
            }
            null -> {
                // После force-kill pref мог остаться true — не restore, только cleanup.
                SessionTrace.mark("SilentVpnService.onStartCommand", "STICKY after kill — cleanup")
                VpnConnectHelper.ensureCleanSlate(this)
                stopSelf()
                return START_NOT_STICKY
            }
        }
        return START_STICKY
    }

    private fun connect(configJson: String, forceBootstrap: Boolean = false) {
        try {
            val obj = JSONObject(configJson)
            val hashes = mutableListOf<String>()
            val arr = obj.optJSONArray("vk_hashes")
            if (arr != null) for (i in 0 until arr.length()) hashes.add(arr.getString(i))

            val deviceId = obj.optString("device_id").ifBlank {
                obj.optString("deviceId").ifBlank { "android" }
            }

            val vpnConfig = runCatching { Gson().fromJson(configJson, VpnConfig::class.java) }.getOrNull()
            // apiWg — только fallback если GETCONF не пришёл за ~10 с (не ранний подъём WG).
            val apiWg = vpnConfig?.let { WireGuardConfigBuilder.fromVpnConfig(it) }

            val bootHash = SilentPrefs.open(this)
                .getString(SilentRepository.PREF_BOOTSTRAP_HASH, null)?.trim().orEmpty()
            val isBootstrap = forceBootstrap || deviceId.startsWith("boot:")
            val rawHashes = HashParser.normalizeList(hashes).filter { it.isNotBlank() }.distinct()
            val savedServerHashes = if (isBootstrap) emptyList() else loadSavedServerHashes()
            val wdttHashes = when {
                isBootstrap -> {
                    val h = rawHashes.firstOrNull { it.isNotBlank() }
                        ?: bootHash.takeIf { it.isNotBlank() }
                    listOfNotNull(h?.trim()?.takeIf { it.isNotBlank() })
                }
                savedServerHashes.isNotEmpty() -> savedServerHashes
                else -> rawHashes
                    .filter { bootHash.isEmpty() || it != bootHash }
                    .take(HashChannelHelper.MAX_HASHES)
            }
            val savedActive = loadSavedActiveServerHashCount()
            val activeHashCount = if (isBootstrap) {
                1
            } else {
                maxOf(wdttHashes.size, savedActive, 1).coerceAtMost(HashChannelHelper.MAX_HASHES)
            }
            // GETCONF: device_id из конфига (boot:fp / UUID backend). Не ANDROID_ID — на Silent VPS
            // пул 10.66.66.2–250; новый id при исчерпании пула → NOCONF.
            val libclientDeviceId = deviceId
            // Bootstrap: app в туннеле (10.66.66.0/24). Main: app вне WG — libclient/TURN напрямую.
            SilentRepository.APP_EXCLUDED_FROM_VPN = !isBootstrap
            val totalWorkers = if (isBootstrap) {
                HashChannelHelper.WORKERS_PER_GROUP
            } else {
                val configWorkers = vpnConfig?.stream_count?.takeIf {
                    it >= HashChannelHelper.WORKERS_PER_GROUP
                }
                if (configWorkers != null) {
                    HashChannelHelper.workersForLibclient(configWorkers, activeHashCount)
                } else {
                    repoResolveTotalWorkers(activeHashCount)
                }
            }
            val libclientHashes = if (isBootstrap) {
                wdttHashes.firstOrNull { it.isNotBlank() }?.let { listOf(it.trim()) } ?: emptyList()
            } else {
                HashChannelHelper.hashesForLibclient(wdttHashes, totalWorkers)
            }

            WdttTunnelManager.start(
                this,
                WdttTunnelManager.Params(
                    serverIp = obj.getString("server_ip"),
                    serverPort = obj.getInt("server_port"),
                    vkHashes = libclientHashes.ifEmpty { wdttHashes },
                    wdttPassword = obj.getString("wdtt_password"),
                    deviceId = libclientDeviceId,
                    workers = totalWorkers,
                    activeHashCount = activeHashCount,
                    captchaMode = "auto",
                    apiWgConfig = apiWg,
                    isBootstrap = isBootstrap,
                ),
                isSwitching = false,
            )
            DebugLog.i(
                "VpnService",
                "WDTT n=$totalWorkers vk=${libclientHashes.size}/$activeHashCount hashes",
            )
            isRunning = true
            SessionTrace.mark("SilentVpnService.connect", "isRunning=true")
            VpnTileHelper.requestUpdate(this)
        } catch (e: Exception) {
            SessionTrace.warn("SilentVpnService.connect", e.message ?: "failed")
            DebugLog.e("VpnService", "connect failed", e)
            isRunning = false
            VpnTileHelper.requestUpdate(this)
            releaseWakeLock()
            releaseWifiLock()
            clearVpnNotification()
            stopSelf()
        }
    }

    private fun disconnect() {
        if (!isRunning && !WdttTunnelManager.running.value) {
            VpnTileHelper.requestUpdate(this)
            stopSelf()
            return
        }
        DebugLog.i("VpnService", "DISCONNECT")
        isRunning = false
        SessionTrace.mark("SilentVpnService.disconnect", "isRunning=false")
        VpnServiceTracker.markSessionActive(this, false)
        teardownVpnOwnershipMonitor()
        VpnTileHelper.requestUpdate(this)
        transportWatchdogJob?.cancel()
        statsUpdaterJob?.cancel()
        isTunnelPaused = false
        activeNetworks.clear()
        performanceLocksHeld = false
        lastNotifBody = ""
        lastNotifUpdateMs = 0L
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        teardownNetworkCallback()
        clearVpnNotification()
        VpnBackendSync.stop()
        WdttTunnelManager.prepareForShutdown()
        scope.launch(Dispatchers.IO) {
            val repo = EntryPointAccessors.fromApplication(
                applicationContext,
                AppEntryPoint::class.java,
            ).silentRepository()
            val notifyJob = if (repo.isLoggedIn() && WdttTunnelManager.tunnelReady.value) {
                async {
                    runCatching { VpnBackendSync.notifyDisconnect(this@SilentVpnService) }
                }
            } else {
                null
            }
            withTimeoutOrNull(1_500L) { notifyJob?.await() }
            if (isRunning) {
                SessionTrace.mark("SilentVpnService.disconnect", "skipped teardown — reconnected")
                return@launch
            }
            WdttTunnelManager.stopAndAwait()
            withContext(Dispatchers.Main) {
                if (isRunning) return@withContext
                releaseWakeLock()
                releaseWifiLock()
                stopSelf()
            }
        }
    }

    /** Убрать уведомление из шторки — только когда VPN выключен (только main thread). */
    private fun clearVpnNotification() {
        runCatching {
            stopForeground(STOP_FOREGROUND_REMOVE)
            getSystemService(NotificationManager::class.java)?.cancel(NOTIF_ID)
        }
    }

    private fun setupNetworkCallback() {
        if (networkCallback != null) return
        connectivityManager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        activeNetworks.clear()
        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                val wasEmpty = activeNetworks.isEmpty()
                activeNetworks.add(network)
                // Не трогаем libclient при каждом onAvailable (видео/LTE) — только после полной потери.
                if (wasEmpty && isRunning && WdttTunnelManager.running.value && WdttTunnelManager.tunnelReady.value) {
                    handleNetworkChange()
                }
            }

            override fun onLost(network: Network) {
                activeNetworks.remove(network)
                // Не kill libclient при кратковременном пропадании сети.
            }
        }
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        connectivityManager?.registerNetworkCallback(request, networkCallback!!)
    }

    private fun handleNetworkChange() {
        val now = System.currentTimeMillis()
        if (now - lastNetworkChangeTime < NETWORK_CHANGE_DEBOUNCE_MS) return
        lastNetworkChangeTime = now
        if (WdttTunnelManager.isNetworkRecoverySuppressed()) return
        if (!isRunning || !WdttTunnelManager.running.value || !WdttTunnelManager.tunnelReady.value) return
        if (System.currentTimeMillis() - connectStartedAtMs < NETWORK_GRACE_MS) return
        if (activeNetworks.isEmpty()) return
        WdttTunnelManager.restartTransport()
    }

    private fun startTransportWatchdog() {
        transportWatchdogJob?.cancel()
        transportWatchdogJob = scope.launch {
            delay(1000)
            while (isActive && isRunning) {
                // Как reference: только libclient — без disconnect при кратковременном WG reload.
                if (!WdttTunnelManager.running.value && !isTunnelPaused) {
                    stopSelf()
                    break
                }
                delay(2000)
            }
        }
    }

    private fun teardownNetworkCallback() {
        networkCallback?.let { runCatching { connectivityManager?.unregisterNetworkCallback(it) } }
        networkCallback = null
    }

    /** Отключиться только если другой VPN реально захватил сеть (uid ≠ наш). */
    private fun setupVpnOwnershipMonitor() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        if (vpnOwnerCallback != null) return
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val ourUid = applicationInfo.uid
        vpnOwnerCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (!isRunning) return
                if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) return
                val owner = VpnNetworkHelper.vpnOwnerUid(cm, network)
                if (owner <= 0 || owner == ourUid) return
                DebugLog.w("VpnService", "Another VPN owns network (uid=$owner) — stopping Silent")
                disconnect()
            }
        }
        val request = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_VPN)
            .build()
        runCatching { cm.registerNetworkCallback(request, vpnOwnerCallback!!) }
    }

    private fun teardownVpnOwnershipMonitor() {
        vpnOwnerCallback?.let { cb ->
            runCatching {
                (getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager)
                    .unregisterNetworkCallback(cb)
            }
        }
        vpnOwnerCallback = null
    }

    private fun acquirePerformanceLocks() {
        performanceLocksHeld = true
        acquireWakeLock()
        // WifiLock HIGH_PERF/LLOW_LATENCY греет чип — достаточно wake lock на этапе connect.
    }

    /** После стабильного подключения — не держать CPU/Wi‑Fi awake (экономия батареи). */
    private fun releasePerformanceLocks() {
        if (!performanceLocksHeld) return
        performanceLocksHeld = false
        releaseWakeLock()
        releaseWifiLock()
    }

    private fun acquireWakeLock() {
        if (wakeLock?.isHeld == true) return
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "silent:tunnel_cpu").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    @Suppress("DEPRECATION")
    private fun acquireWifiLock() {
        if (wifiLock?.isHeld == true) return
        val wm = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
        val mode = if (Build.VERSION.SDK_INT >= 29) {
            WifiManager.WIFI_MODE_FULL_LOW_LATENCY
        } else {
            WifiManager.WIFI_MODE_FULL_HIGH_PERF
        }
        wifiLock = wm.createWifiLock(mode, "silent:wifi_perf").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun releaseWakeLock() {
        if (wakeLock?.isHeld == true) wakeLock?.release()
        wakeLock = null
    }

    private fun releaseWifiLock() {
        if (wifiLock?.isHeld == true) wifiLock?.release()
        wifiLock = null
    }

    private fun startFg(notification: Notification) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIF_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(NOTIF_ID, notification)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Silent VPN",
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = "Статус VPN и скорость"
                setShowBadge(true)
            }
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }

    private fun openAppIntent(): PendingIntent =
        PendingIntent.getActivity(
            this,
            1,
            MainActivity.openIntent(this),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    private fun notificationTitle(ready: Boolean): String = when {
        ready -> "Silent VPN — подключено"
        else -> "Silent VPN — подключение…"
    }

    private fun notificationBody(ready: Boolean, stats: String): String {
        val trimmed = stats.trim()
        if (ready && trimmed.isNotBlank() && trimmed != "Ожидание данных…") return trimmed
        return when {
            ready -> "Туннель активен"
            else -> "Подключение к серверу…"
        }
    }

    /** Минимальное FG-уведомление на время подключения (Android требует для foreground service). */
    private fun buildConnectingNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_silent)
            .setContentTitle("Silent VPN — подключение…")
            .setContentText("Подключение к серверу…")
            .setContentIntent(openAppIntent())
            .setOngoing(false)
            .setSilent(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_SECRET)
            .build()

    private fun buildActiveNotification(stats: String): Notification {
        val body = notificationBody(ready = true, stats = stats)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_silent)
            .setContentTitle(notificationTitle(ready = true))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    private fun postVpnNotification(stats: String) {
        if (!isRunning || !WdttTunnelManager.tunnelReady.value) return
        val body = notificationBody(ready = true, stats = stats)
        val now = System.currentTimeMillis()
        if (body == lastNotifBody && now - lastNotifUpdateMs < NOTIF_UPDATE_MIN_MS) return
        if (now - lastNotifUpdateMs < NOTIF_UPDATE_MIN_MS && lastNotifBody.isNotBlank()) return
        lastNotifUpdateMs = now
        lastNotifBody = body
        val notification = buildActiveNotification(stats)
        startFg(notification)
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, notification)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onTaskRemoved(rootIntent: Intent?) {
        SessionTrace.mark("SilentVpnService.onTaskRemoved", "app swiped away running=$isRunning")
        if (isRunning) {
            // Не пишем vpn_session_active=true — при force-kill pref ломает reconnect по плитке.
            val stats = WdttTunnelManager.stats.value
            runCatching {
                if (WdttTunnelManager.tunnelReady.value) {
                    startFg(buildActiveNotification(stats))
                } else {
                    startFg(buildConnectingNotification())
                }
            }
        } else {
            VpnServiceTracker.markSessionActive(this, false)
        }
        VpnTileHelper.requestUpdate(this)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        SessionTrace.enter("SilentVpnService.onDestroy")
        stopTunnelLocal(awaitStop = true, stopService = false)
        SessionTrace.exit("SilentVpnService.onDestroy")
        super.onDestroy()
    }

    /** Как stopTunnel() в reference TunnelService. */
    private fun stopTunnelLocal(awaitStop: Boolean = false, stopService: Boolean = true) {
        transportWatchdogJob?.cancel()
        statsUpdaterJob?.cancel()
        isRunning = false
        isTunnelPaused = false
        activeNetworks.clear()
        VpnServiceTracker.markSessionActive(this, false)
        VpnBackendSync.stop()
        backendSyncTriggered = false
        teardownNetworkCallback()
        teardownVpnOwnershipMonitor()
        performanceLocksHeld = false
        lastNotifBody = ""
        lastNotifUpdateMs = 0L
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        runCatching {
            if (awaitStop) {
                runBlocking { WdttTunnelManager.stopAndAwait() }
            } else {
                scope.launch { WdttTunnelManager.stopAndAwait() }
            }
        }
        releaseWakeLock()
        releaseWifiLock()
        clearVpnNotification()
        VpnTileHelper.requestUpdate(this)
        if (stopService) stopSelf()
    }

    private fun loadSavedServerHashes(): List<String> {
        val json = SilentPrefs.open(this)
            .getString(SilentRepository.PREF_SAVED_HASH_ITEMS, null) ?: return emptyList()
        val items = runCatching {
            val type = object : TypeToken<List<HashItemDto>>() {}.type
            Gson().fromJson<List<HashItemDto>>(json, type)
        }.getOrDefault(emptyList())
        return HashParser.normalizeList(
            items.filter {
                it.source != "bootstrap" && it.is_active && it.status == "active" && it.hash.isNotBlank()
            }.map { it.hash.trim() },
        ).filter { it.isNotBlank() }.distinct().take(HashChannelHelper.MAX_HASHES)
    }

    private fun loadSavedActiveServerHashCount(): Int = loadSavedServerHashes().size

    private fun repoResolveTotalWorkers(activeHashCount: Int): Int {
        val prefs = SilentPrefs.open(this)
        val activeHashes = activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES)
        val max = HashChannelHelper.maxTotalWorkers(activeHashes)
        val saved = when {
            prefs.contains(SilentRepository.PREF_HASH_TOTAL_WORKERS) -> {
                val raw = prefs.getInt(
                    SilentRepository.PREF_HASH_TOTAL_WORKERS,
                    HashChannelHelper.WORKERS_PER_GROUP,
                )
                if (raw > max) max else HashChannelHelper.normalizeTotalWorkers(raw, activeHashes)
            }
            prefs.contains(SilentRepository.PREF_HASH_CHANNELS_PER_HASH) &&
                !prefs.getBoolean(SilentRepository.PREF_HASH_LEGACY_MIGRATED, false) -> {
                HashChannelHelper.migrateLegacyPerHash(
                    prefs.getInt(
                        SilentRepository.PREF_HASH_CHANNELS_PER_HASH,
                        HashChannelHelper.WORKERS_PER_GROUP,
                    ),
                    activeHashes,
                )
            }
            else -> HashChannelHelper.normalizeTotalWorkers(
                HashChannelHelper.WORKERS_PER_GROUP * 4,
                activeHashes,
            )
        }
        return HashChannelHelper.workersForLibclient(saved, activeHashes)
    }
}
