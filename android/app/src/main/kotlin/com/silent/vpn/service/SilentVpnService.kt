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
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardConfigBuilder
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
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
        private const val NETWORK_GRACE_MS = 90_000L
        private const val NETWORK_DEBOUNCE_MS = 12_000L
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

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        acquireWakeLock()
        scope.launch {
            combine(
                WdttTunnelManager.tunnelReady,
                WdttTunnelManager.stats,
                WdttTunnelManager.running,
            ) { ready, stats, wdttRunning ->
                Triple(ready, stats, wdttRunning)
            }.collectLatest { (ready, stats, wdttRunning) ->
                if (!isRunning && !wdttRunning) return@collectLatest
                postVpnNotification(ready, stats)
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
                setupNetworkCallback()
                acquireWakeLock()
                acquireWifiLock()
                startFg(buildNotification(connecting = true))
                connect(configJson)
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

            val hashCount = hashes.size.coerceAtLeast(1)
            val maxWorkers = if (isCellularNetwork()) 6 else 12
            val workerCount = (vpnConfig?.stream_count ?: (hashCount * 3).coerceAtLeast(6))
                .coerceIn(3, maxWorkers)

            WdttTunnelManager.start(
                this,
                WdttTunnelManager.Params(
                    serverIp = obj.getString("server_ip"),
                    serverPort = obj.getInt("server_port"),
                    vkHashes = hashes,
                    wdttPassword = obj.getString("wdtt_password"),
                    deviceId = deviceId,
                    workers = workerCount,
                    captchaMode = "auto",
                    apiWgConfig = apiWg,
                ),
            )
            DebugLog.i("VpnService", "WDTT workers=$workerCount hashes=$hashCount")
            isRunning = true
            postVpnNotification(WdttTunnelManager.tunnelReady.value, WdttTunnelManager.stats.value)
        } catch (e: Exception) {
            DebugLog.e("VpnService", "connect failed", e)
            isRunning = false
            releaseWakeLock()
            releaseWifiLock()
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun disconnect() {
        DebugLog.i("VpnService", "DISCONNECT")
        teardownNetworkCallback()
        WdttTunnelManager.stop()
        isRunning = false
        releaseWakeLock()
        releaseWifiLock()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun setupNetworkCallback() {
        if (networkCallback != null) return
        connectivityManager = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        networkCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onCapabilitiesChanged(network: Network, caps: NetworkCapabilities) {
                if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return
                if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) return
                val transport = when {
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ->
                        NetworkCapabilities.TRANSPORT_WIFI
                    caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ->
                        NetworkCapabilities.TRANSPORT_CELLULAR
                    else -> return
                }
                val prev = lastTransport
                lastTransport = transport
                if (prev == null || prev == transport) return
                if (!canRestartForNetwork()) return
                DebugLog.i("VpnService", "Смена транспорта $prev → $transport — restartTransport")
                handleNetworkChange()
            }
        }
        val request = NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            .build()
        connectivityManager?.registerNetworkCallback(request, networkCallback!!)
    }

    private fun teardownNetworkCallback() {
        networkCallback?.let { runCatching { connectivityManager?.unregisterNetworkCallback(it) } }
        networkCallback = null
        lastTransport = null
    }

    private fun canRestartForNetwork(): Boolean {
        if (!isRunning) return false
        if (System.currentTimeMillis() - connectStartedAtMs < NETWORK_GRACE_MS) return false
        if (!WdttTunnelManager.tunnelReady.value) return false
        if (WdttTunnelManager.activeWorkers.value < 1) return false
        return true
    }

    private fun isCellularNetwork(): Boolean {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return false
        return caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) &&
            !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
    }

    private fun handleNetworkChange() {
        val now = System.currentTimeMillis()
        if (now - lastNetworkChangeTime < NETWORK_DEBOUNCE_MS) return
        lastNetworkChangeTime = now
        if (WdttTunnelManager.running.value) {
            WdttTunnelManager.restartTransport()
        }
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

    private fun notificationTitle(ready: Boolean, connecting: Boolean): String = when {
        ready -> "Silent VPN — подключено"
        connecting -> "Silent VPN — подключение…"
        else -> "Silent VPN"
    }

    private fun notificationBody(ready: Boolean, stats: String, connecting: Boolean): String {
        if (stats.isNotBlank()) return stats.trim()
        return when {
            ready -> "Туннель активен"
            connecting -> "Подключение к серверу…"
            else -> "Ожидание…"
        }
    }

    private fun buildNotification(ready: Boolean = false, stats: String = "", connecting: Boolean = false): Notification {
        val body = notificationBody(ready, stats, connecting)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_silent)
            .setContentTitle(notificationTitle(ready, connecting))
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(openAppIntent())
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .build()
    }

    private fun postVpnNotification(ready: Boolean, stats: String) {
        if (!isRunning) return
        val notification = buildNotification(
            ready = ready,
            stats = stats,
            connecting = !ready,
        )
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, notification)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        teardownNetworkCallback()
        WdttTunnelManager.stop()
        isRunning = false
        releaseWakeLock()
        releaseWifiLock()
        super.onDestroy()
    }
}
