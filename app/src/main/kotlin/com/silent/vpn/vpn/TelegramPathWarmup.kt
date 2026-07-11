package com.silent.vpn.vpn

import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import java.net.InetSocketAddress
import java.net.Socket
import java.net.InetAddress

/**
 * Прогрев DC/CDN Telegram через VPN — паритет с PC 1.0.154.
 * Превью/медиа чувствительнее к «холодному» пути, чем скачивание файлов.
 */
object TelegramPathWarmup {
    private const val TAG = "TgWarmup"

    private val tcpTargets = listOf(
        "149.154.175.50" to 443,
        "149.154.175.100" to 443,
        "149.154.167.51" to 443,
        "149.154.167.91" to 443,
        "91.108.56.165" to 443,
        "91.108.4.134" to 443,
        "91.108.8.68" to 443,
        "149.154.167.51" to 5222,
        "149.154.175.50" to 5222,
        "91.108.56.165" to 5222,
        "api.telegram.org" to 443,
    )

    private val dnsNames = listOf(
        "api.telegram.org",
        "telegram.org",
        "core.telegram.org",
        "cdn1.telegram.org",
        "cdn2.telegram.org",
        "cdn3.telegram.org",
        "cdn4.telegram.org",
        "venus.web.telegram.org",
        "flora.web.telegram.org",
    )

    @Volatile
    private var retryJob: Job? = null

    fun cancel() {
        retryJob?.cancel()
        retryJob = null
    }

    /** Сразу + повтор через 4с / 12с (когда воркеры догонят). */
    fun schedule(scope: CoroutineScope) {
        cancel()
        retryJob = scope.launch(Dispatchers.IO) {
            runOnce()
            delay(4_000)
            if (WdttTunnelManager.tunnelReady.value && !WdttTunnelManager.isBootstrapMode()) {
                runOnce()
            }
            delay(8_000)
            if (WdttTunnelManager.tunnelReady.value && !WdttTunnelManager.isBootstrapMode()) {
                runOnce()
            }
        }
    }

    private fun runOnce() {
        DebugLog.i(TAG, "warmup Telegram DC/CDN (workers=${WdttTunnelManager.activeWorkers.value})")
        for (name in dnsNames) {
            runCatching { InetAddress.getByName(name) }
        }
        for ((host, port) in tcpTargets) {
            runCatching {
                Socket().use { s ->
                    s.soTimeout = 5_000
                    s.connect(InetSocketAddress(host, port), 5_000)
                }
            }
        }
    }
}
