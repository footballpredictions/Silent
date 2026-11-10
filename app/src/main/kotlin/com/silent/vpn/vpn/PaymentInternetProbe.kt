package com.silent.vpn.vpn

import android.content.Context
import com.silent.vpn.service.SilentVpnService
import kotlinx.coroutines.delay
import okhttp3.ConnectionPool
import okhttp3.Dns
import okhttp3.OkHttpClient
import java.net.Proxy
import java.util.concurrent.TimeUnit

internal object PaymentInternetProbe {
    suspend fun check(context: Context): Boolean {
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
        return try {
            PaymentHttpsProbe.check(client)
        } finally {
            client.connectionPool.evictAll()
            client.dispatcher.executorService.shutdown()
        }
    }
}
