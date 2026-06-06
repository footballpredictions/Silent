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
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardConfigBuilder
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.silent.vpn.data.HashItemDto
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Foreground VPN service — сеть/LTE как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * WakeLock, WifiLock, NetworkCallback (NOT_VPN), pause/resume и restartTransport при смене Wi‑Fi ↔ LTE.
 */
class SilentVpnService : Service() {

    companion object {
        private const val CHANNEL_ID = "silent_vpn"
        private const val NOTIF_ID = 1001
        /** Не перезапускать libclient сразу после WireGuard — иначе ломается вход. */
        /** Не трогать libclient в первые секунды первого connect. */
        private const val NETWORK_GRACE_MS = 90_000L
        /** После tunnelReady переключение Wi‑Fi/LTE можно обрабатывать раньше. */
        private const val NETWORK_GRACE_AFTER_READY_MS = 12_000L
        private const val NETWORK_DEBOUNCE_MS = 8_000L
        private const val TRANSPORT_WATCHDOG_MS = 180_000L
        private const val NOTIF_UPDATE_MIN_MS = 3_000L
        const val ACTION_CONNECT = "com.silent.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.silent.vpn.DISCONNECT"
        const val EXTRA_CONFIG = "vpn_config_json"
        var isRunning = false
            private set
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var connectivityManager: ConnectivityManager? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private var lastTransport: Int? = null
    private var lastNetworkChangeTime = 0L
    private var connectStartedAtMs = 0L
    private var lastUnderlyingInternet: Boolean? = null
    private var pausedForNetwork = false
    private var networkRecoveryJob: Job? = null
    private var transportWatchdogJob: Job? = null
    private var statsUpdaterJob: Job? = null
    private var performanceLocksHeld = false
    private var lastNotifUpdateMs = 0L
    private var lastNotifBody = ""

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    /** Как в proxy-turn-vk-android: отдельный цикл обновления уведомления (переживает reconnect). */
    private fun startStatsUpdater() {
        statsUpdaterJob?.cancel()
        statsUpdaterJob = scope.launch {
            delay(1000)
            while (isActive && isRunning) {
                val stats = WdttTunnelManager.stats.value
                if (WdttTunnelManager.isInternetReady()) {
                    releasePerformanceLocks()
                    postVpnNotification(stats)
                } else if (WdttTunnelManager.running.value) {
                    startFg(buildConnectingNotification())
                }
                delay(3000)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                val configJson = intent.getStringExtra(EXTRA_CONFIG)
                if (configJson == null) {
                    DebugLog.e("VpnService", "CONNECT without config")
                    stopSelf()
                    return START_NOT_STICKY
                }
                DebugLog.i(
                    "VpnService",
                    "CONNECT device=${runCatching { JSONObject(configJson).optString("device_id") }.getOrNull()?.take(8)}",
                )
                connectStartedAtMs = System.currentTimeMillis()
                lastTransport = null
                lastNetworkChangeTime = 0L
                lastNotifBody = ""
                lastNotifUpdateMs = 0L
                setupNetworkCallback()
                startTransportWatchdog()
                startStatsUpdater()
                acquirePerformanceLocks()
                startFg(buildConnectingNotification())
                connect(configJson)
                VpnTileHelper.requestUpdate(this)
            }
            ACTION_DISCONNECT -> disconnect()
        }
        return START_STICKY
    }

    private fun connect(configJson: String) {
        try {
            val obj = JSONObject(configJson)
            val hashes = mutableListOf<String>()
            val arr = obj.optJSONArray("vk_hashes")
            if (arr != null) for (i in 0 until arr.length()) hashes.add(arr.getString(i))

            val deviceId = obj.optString("device_id").ifBlank {
                obj.optString("deviceId").ifBlank { "android" }
            }

            val vpnConfig = runCatching { Gson().fromJson(configJson, VpnConfig::class.java) }.getOrNull()
            val apiWg = vpnConfig?.let { WireGuardConfigBuilder.fromVpnConfig(it) }

            val bootHash = SilentPrefs.open(this)
                .getString(SilentRepository.PREF_BOOTSTRAP_HASH, null)?.trim().orEmpty()
            val serverHashes = hashes.filter { it.isNotBlank() && it != bootHash }
                .distinct()
                .take(HashChannelHelper.MAX_HASHES)
            val wdttHashes = if (serverHashes.isNotEmpty()) serverHashes else hashes.take(HashChannelHelper.MAX_HASHES)
            val savedActive = loadSavedActiveServerHashCount()
            val activeHashCount = maxOf(wdttHashes.size, savedActive, 1)
                .coerceAtMost(HashChannelHelper.MAX_HASHES)
            val isBootstrap = deviceId.startsWith("boot:")
            // Silent всегда вне WG (libclient/TURN напрямую). API — overlay с split AllowedIPs.
            SilentRepository.APP_EXCLUDED_FROM_VPN = true
            val totalWorkers = if (isBootstrap) {
                (vpnConfig?.stream_count ?: 9).coerceIn(3, 9)
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

            val switching = WdttTunnelManager.running.value && !isBootstrap
            WdttTunnelManager.start(
                this,
                WdttTunnelManager.Params(
                    serverIp = obj.getString("server_ip"),
                    serverPort = obj.getInt("server_port"),
                    vkHashes = libclientHashes.ifEmpty { wdttHashes },
                    wdttPassword = obj.getString("wdtt_password"),
                    deviceId = deviceId,
                    workers = totalWorkers,
                    activeHashCount = activeHashCount,
                    captchaMode = "auto",
                    apiWgConfig = apiWg,
                    isBootstrap = isBootstrap,
                ),
                isSwitching = switching,
            )
            DebugLog.i(
                "VpnService",
                "WDTT n=$totalWorkers vk=${libclientHashes.size}/$activeHashCount hashes",
            )
            isRunning = true
            VpnTileHelper.requestUpdate(this)
        } catch (e: Exception) {
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
        DebugLog.i("VpnService", "DISCONNECT")
        isRunning = false
        VpnTileHelper.requestUpdate(this)
        performanceLocksHeld = false
        lastNotifBody = ""
        lastNotifUpdateMs = 0L
        networkRecoveryJob?.cancel()
        transportWatchdogJob?.cancel()
        statsUpdaterJob?.cancel()
        pausedForNetwork = false
        lastUnderlyingInternet = null
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        teardownNetworkCallback()
        clearVpnNotification()
        scope.launch(Dispatchers.IO) {
            WdttTunnelManager.stopAndAwait()
            withContext(Dispatchers.Main) {
                clearVpnNotification()
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
        lastUnderlyingInternet = VpnNetworkHelper.hasUnderlyingInternet(this)
        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                scheduleNetworkRecovery(1500) { handleNetworkRestored() }
            }

            override fun onLost(network: Network) {
                scheduleNetworkRecovery(2000) { handleNetworkLost() }
            }

            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) return
                val hasInternet = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                val prev = lastUnderlyingInternet
                lastUnderlyingInternet = hasInternet
                if (prev != null && !hasInternet && prev) {
                    scheduleNetworkRecovery(2000) { handleNetworkLost() }
                } else if (prev == false && hasInternet) {
                    scheduleNetworkRecovery(1500) { handleNetworkRestored() }
                }

                if (!hasInternet) return
                val transport = when {
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ->
                        NetworkCapabilities.TRANSPORT_WIFI
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ->
                        NetworkCapabilities.TRANSPORT_CELLULAR
                    else -> return
                }
                val prevTransport = lastTransport
                lastTransport = transport
                if (prevTransport == null || prevTransport == transport) return
                if (WdttTunnelManager.isNetworkRecoverySuppressed()) return
                if (!canRestartForNetwork()) return
                DebugLog.i("VpnService", "Смена транспорта $prevTransport → $transport — restartTransport")
                pausedForNetwork = false
                handleTransportChange()
            }
        }
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        connectivityManager?.registerNetworkCallback(request, networkCallback!!)
    }

    private fun scheduleNetworkRecovery(delayMs: Long, action: () -> Unit) {
        networkRecoveryJob?.cancel()
        networkRecoveryJob = scope.launch {
            delay(delayMs.toLong())
            if (isRunning) action()
        }
    }

    private fun handleNetworkLost() {
        if (!isRunning || pausedForNetwork) return
        if (WdttTunnelManager.isNetworkRecoverySuppressed()) return
        if (!WdttTunnelManager.running.value) return
        if (System.currentTimeMillis() - connectStartedAtMs < NETWORK_GRACE_MS) return
        if (!WdttTunnelManager.tunnelReady.value) return
        DebugLog.i("VpnService", "Потеря сети (звонок/разрыв) — pause libclient")
        pausedForNetwork = true
        WdttTunnelManager.pause()
    }

    private fun handleNetworkRestored() {
        if (!isRunning) return
        if (!VpnNetworkHelper.hasUnderlyingInternet(this)) return
        recoverTransportAfterNetwork("сеть восстановлена")
    }

    private fun handleTransportChange() {
        val now = System.currentTimeMillis()
        if (now - lastNetworkChangeTime < NETWORK_DEBOUNCE_MS) return
        lastNetworkChangeTime = now
        recoverTransportAfterNetwork("смена Wi‑Fi ↔ мобильная")
    }

    /**
     * После звонка, обрыва или смены транспорта — поднять libclient снова (WG не трогаем).
     */
    private fun recoverTransportAfterNetwork(reason: String) {
        if (!isRunning) return
        if (WdttTunnelManager.isNetworkRecoverySuppressed()) return
        if (WdttTunnelManager.isWorkerRampUpActive()) return
        if (!VpnNetworkHelper.hasUnderlyingInternet(this)) return
        val elapsed = System.currentTimeMillis() - connectStartedAtMs
        val wasPaused = pausedForNetwork
        val ready = WdttTunnelManager.tunnelReady.value
        val graceLimit = if (ready) NETWORK_GRACE_AFTER_READY_MS else NETWORK_GRACE_MS
        if (!wasPaused && elapsed < graceLimit) return
        if (!wasPaused && !ready) return

        val healthy = WdttTunnelManager.isTransportHealthy()
        if (!wasPaused && healthy) return

        DebugLog.i(
            "VpnService",
            "Восстановление транспорта ($reason): paused=$wasPaused healthy=$healthy workers=${WdttTunnelManager.activeWorkers.value}",
        )
        pausedForNetwork = false
        acquireTransientWakeLock()
        when {
            wasPaused || !WdttTunnelManager.running.value -> WdttTunnelManager.resume()
            !healthy -> WdttTunnelManager.restartTransport()
            else -> WdttTunnelManager.restartTransport()
        }
    }

    /** Периодически: туннель «подключён», но libclient мёртв — перезапуск без действий пользователя. */
    private fun startTransportWatchdog() {
        transportWatchdogJob?.cancel()
        transportWatchdogJob = scope.launch {
            while (isRunning) {
                delay(TRANSPORT_WATCHDOG_MS)
                if (!isRunning) break
                if (pausedForNetwork) continue
                if (!VpnNetworkHelper.hasUnderlyingInternet(this@SilentVpnService)) continue
                if (!WdttTunnelManager.tunnelReady.value) continue
                val elapsed = System.currentTimeMillis() - connectStartedAtMs
                if (elapsed < NETWORK_GRACE_AFTER_READY_MS) continue
                if (WdttTunnelManager.isTransportHealthy()) continue
                scheduleNetworkRecovery(2000) {
                    recoverTransportAfterNetwork("watchdog")
                }
            }
        }
    }

    private fun teardownNetworkCallback() {
        networkCallback?.let { runCatching { connectivityManager?.unregisterNetworkCallback(it) } }
        networkCallback = null
        lastTransport = null
    }

    private fun canRestartForNetwork(): Boolean {
        if (!isRunning) return false
        val elapsed = System.currentTimeMillis() - connectStartedAtMs
        val grace = if (WdttTunnelManager.tunnelReady.value) {
            NETWORK_GRACE_AFTER_READY_MS
        } else {
            NETWORK_GRACE_MS
        }
        if (elapsed < grace) return false
        if (!WdttTunnelManager.tunnelReady.value) return false
        return true
    }

    private fun isCellularNetwork(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) &&
            !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
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

    private fun acquireTransientWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        runCatching {
            pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "silent:transport_recover").apply {
                setReferenceCounted(false)
                acquire(30_000L)
            }
        }
    }

    private fun isOnWifi(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
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
        if (!isRunning || !WdttTunnelManager.isInternetReady()) return
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

    override fun onDestroy() {
        teardownNetworkCallback()
        WdttTunnelManager.stop()
        isRunning = false
        VpnTileHelper.requestUpdate(this)
        releaseWakeLock()
        releaseWifiLock()
        clearVpnNotification()
        super.onDestroy()
    }

    private fun loadSavedActiveServerHashCount(): Int {
        val json = SilentPrefs.open(this)
            .getString(SilentRepository.PREF_SAVED_HASH_ITEMS, null) ?: return 0
        val items = runCatching {
            val type = object : TypeToken<List<HashItemDto>>() {}.type
            Gson().fromJson<List<HashItemDto>>(json, type)
        }.getOrDefault(emptyList())
        return items.count {
            it.source != "bootstrap" && it.is_active && it.status == "active" && it.hash.isNotBlank()
        }
    }

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
