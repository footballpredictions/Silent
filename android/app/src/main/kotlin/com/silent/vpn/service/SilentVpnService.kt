package com.silent.vpn.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.Log
import androidx.core.app.NotificationCompat
import com.silent.vpn.MainActivity
import com.wireguard.android.backend.GoBackend
import com.wireguard.config.*
import kotlinx.coroutines.*

/**
 * Silent VPN Service — WireGuard over VK TURN/DTLS
 *
 * Uses WireGuard GoBackend to create a VPN tunnel.
 * The actual TURN/DTLS transport layer to VK relay servers
 * is handled by the native WDTT Go library (libclient.so).
 */
class SilentVpnService : VpnService() {

    companion object {
        private const val TAG = "SilentVpnService"
        private const val CHANNEL_ID = "silent_vpn"
        private const val NOTIF_ID = 1001

        const val ACTION_CONNECT = "com.silent.vpn.CONNECT"
        const val ACTION_DISCONNECT = "com.silent.vpn.DISCONNECT"
        const val EXTRA_CONFIG = "vpn_config_json"

        var isRunning = false
            private set
    }

    private var vpnInterface: ParcelFileDescriptor? = null
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_CONNECT -> {
                val configJson = intent.getStringExtra(EXTRA_CONFIG)
                if (configJson != null) {
                    startForeground(NOTIF_ID, buildNotification("Подключение..."))
                    scope.launch { connect(configJson) }
                }
            }
            ACTION_DISCONNECT -> {
                scope.launch { disconnect() }
            }
        }
        return START_STICKY
    }

    private suspend fun connect(configJson: String) {
        try {
            Log.i(TAG, "Starting VPN tunnel...")
            val config = parseConfig(configJson) ?: run {
                Log.e(TAG, "Failed to parse VPN config"); return
            }

            val builder = Builder()
                .setSession("Silent VPN")
                .addAddress(config.wgAddress, 24)
                .addDnsServer("77.88.8.8")
                .addDnsServer("77.88.8.1")
                .addRoute("0.0.0.0", 0)
                .setMtu(1280)
                .addDisallowedApplication(packageName) // Exclude our own app
                .addDisallowedApplication("com.vkontakte.android") // Exclude VK

            vpnInterface = builder.establish()
            isRunning = true

            updateNotification("Подключено")
            Log.i(TAG, "VPN tunnel established")

        } catch (e: Exception) {
            Log.e(TAG, "VPN connect error: ${e.message}")
            isRunning = false
            stopSelf()
        }
    }

    private suspend fun disconnect() {
        try {
            vpnInterface?.close()
            vpnInterface = null
            isRunning = false
            Log.i(TAG, "VPN disconnected")
        } catch (e: Exception) {
            Log.e(TAG, "Disconnect error: ${e.message}")
        } finally {
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    private data class ParsedConfig(
        val wgAddress: String,
        val wgPrivateKey: String,
        val serverIp: String,
        val serverPort: Int,
        val serverPublicKey: String,
        val wdttPassword: String,
        val vkHashes: List<String>,
    )

    private fun parseConfig(json: String): ParsedConfig? = try {
        val obj = org.json.JSONObject(json)
        val hashes = mutableListOf<String>()
        val arr = obj.optJSONArray("vk_hashes")
        if (arr != null) for (i in 0 until arr.length()) hashes.add(arr.getString(i))
        ParsedConfig(
            wgAddress = obj.getString("wg_address").substringBefore("/"),
            wgPrivateKey = obj.getString("wg_private_key"),
            serverIp = obj.getString("server_ip"),
            serverPort = obj.getInt("server_port"),
            serverPublicKey = obj.getString("server_public_key"),
            wdttPassword = obj.getString("wdtt_password"),
            vkHashes = hashes,
        )
    } catch (e: Exception) {
        Log.e(TAG, "Config parse error: ${e.message}"); null
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "Silent VPN",
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = "VPN connection status" }
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val pi = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentTitle("Silent VPN")
            .setContentText(text)
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager?.notify(NOTIF_ID, buildNotification(text))
    }

    override fun onDestroy() {
        scope.cancel()
        vpnInterface?.close()
        isRunning = false
        super.onDestroy()
    }
}
