package com.silent.vpn.vpn

import android.content.Context
import com.silent.vpn.service.SilentVpnService
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.URL
import java.net.HttpURLConnection
import okhttp3.ConnectionPool
import okhttp3.Dns
import okhttp3.OkHttpClient
import java.net.Proxy
import java.util.concurrent.TimeUnit

internal object PaymentInternetProbe {
    suspend fun checkDirect(context: Context): Boolean = withContext(Dispatchers.IO) {
        val network = VpnNetworkHelper.findUnderlyingNetwork(context) ?: return@withContext false
        val client = OkHttpClient.Builder().proxy(Proxy.NO_PROXY).socketFactory(network.socketFactory)
            .dns(object : Dns { override fun lookup(hostname: String) = network.getAllByName(hostname).toList() })
            .connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).callTimeout(4, TimeUnit.SECONDS)
            .followRedirects(false).followSslRedirects(false).build()
        PaymentProbeClient.check(client)
    }

    suspend fun check(context: Context): Boolean {
        if (BrowserScopedTunnel.isRunning()) return withContext(Dispatchers.IO) {
            val connection = URL(BrowserScopedTunnel.OTA_BASE_URL + "/_silent/payment-site").openConnection(Proxy.NO_PROXY) as HttpURLConnection
            try {
                connection.connectTimeout = 1_000
                connection.readTimeout = 5_000
                connection.useCaches = false
                connection.responseCode == 204
            } catch (_: Exception) { false } finally { connection.disconnect() }
        }
        if (!SilentVpnService.isRunning || !WdttTunnelManager.isBootstrapMode() ||
            !WdttTunnelManager.tunnelReady.value) return false
        var network = VpnNetworkHelper.getSilentVpnNetwork(context)
        repeat(10) {
            if (network == null) {
                delay(100)
                network = VpnNetworkHelper.getSilentVpnNetwork(context)
            }
        }
        // No physical-network fallback: it would validate a different path from the browser.
        val vpn = network ?: return false
        val client = OkHttpClient.Builder()
            .proxy(Proxy.NO_PROXY)
            .socketFactory(vpn.socketFactory)
            .dns(object : Dns {
                override fun lookup(hostname: String) = vpn.getAllByName(hostname).toList()
            })
            .connectionPool(ConnectionPool(0, 1, TimeUnit.MILLISECONDS))
            .connectTimeout(2, TimeUnit.SECONDS)
            .readTimeout(2, TimeUnit.SECONDS)
            .callTimeout(4, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
        return PaymentProbeClient.check(client)
    }
}
