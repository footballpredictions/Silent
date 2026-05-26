package com.silent.vpn.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.silent.vpn.MainActivity
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import org.json.JSONObject

class SilentVpnService : Service() {

    companion object {
        private const val CHANNEL_ID = "silent_vpn"
        private const val NOTIF_ID = 1001
        const val ACTION_CONNECT = "com.silent.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.silent.vpn.DISCONNECT"
        const val EXTRA_CONFIG = "vpn_config_json"
        var isRunning = false
            private set
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        scope.launch {
            WdttTunnelManager.stats.collectLatest { stats ->
                if (stats.isNotBlank() && isRunning) updateNotification(stats)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                val configJson = intent.getStringExtra(EXTRA_CONFIG)
                if (configJson == null) { stopSelf(); return START_NOT_STICKY }
                val notification = buildNotification("Подключение...")
                startFg(notification)
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

            WdttTunnelManager.start(
                this,
                WdttTunnelManager.Params(
                    serverIp = obj.getString("server_ip"),
                    serverPort = obj.getInt("server_port"),
                    vkHashes = hashes,
                    wdttPassword = obj.getString("wdtt_password"),
                    deviceId = deviceId,
                ),
            )
            isRunning = true
            updateNotification("Подключение...")
        } catch (e: Exception) {
            isRunning = false
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private fun disconnect() {
        WdttTunnelManager.stop()
        isRunning = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
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
            val channel = NotificationChannel(CHANNEL_ID, "Silent VPN", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentTitle("Silent VPN")
            .setContentText(text)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java)?.notify(NOTIF_ID, buildNotification(text))
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        WdttTunnelManager.stop()
        isRunning = false
        super.onDestroy()
    }
}
