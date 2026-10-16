package com.silent.vpn.service

import android.content.Context
import android.content.ContextWrapper
import android.os.Build
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.BrowserScopedTunnel
import com.silent.vpn.policy.TunnelDataWatch
import android.os.SystemClock
import android.net.ConnectivityManager
import java.net.ServerSocket
import java.net.InetAddress
import kotlin.concurrent.thread
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import kotlin.coroutines.Continuation
import kotlin.coroutines.intrinsics.COROUTINE_SUSPENDED
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertNotSame
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the service -> manager boundary, not just an isolated recovery policy.
 * No real transport, account, server or VPN interface is started by this fixture.
 */
@RunWith(AndroidJUnit4::class)
class ServiceRecoveryRegressionDeviceTest {
    private class TransportProcess : Process() {
        private var alive = true
        val commands = ByteArrayOutputStream()
        override fun getOutputStream() = commands
        override fun getInputStream() = ByteArrayInputStream(byteArrayOf())
        override fun getErrorStream() = ByteArrayInputStream(byteArrayOf())
        override fun waitFor(): Int { alive = false; return 0 }
        override fun waitFor(timeout: Long, unit: TimeUnit): Boolean { alive = false; return true }
        override fun exitValue(): Int = if (alive) throw IllegalThreadStateException() else 0
        override fun destroy() { alive = false }
        override fun isAlive() = alive
        fun stops(): Int = Regex("STOP").findAll(commands.toString("UTF-8")).count()
    }

    private fun managerField(name: String) = WdttTunnelManager::class.java.getDeclaredField(name)
        .apply { isAccessible = true }
    private fun serviceField(name: String) = SilentVpnService::class.java.getDeclaredField(name)
        .apply { isAccessible = true }

    private suspend fun recover(service: SilentVpnService, reason: String): Unit = suspendCoroutine { continuation ->
        try {
            val method = SilentVpnService::class.java.declaredMethods.single {
                it.name == "recoverTransportAfterNetwork"
            }.apply { isAccessible = true }
            val result = if (method.parameterCount == 1) {
                method.invoke(service, reason)
            } else {
                method.invoke(service, reason, continuation)
            }
            if (result !== COROUTINE_SUSPENDED) continuation.resume(Unit)
        } catch (error: java.lang.reflect.InvocationTargetException) {
            continuation.resumeWithException(error.targetException)
        } catch (error: Throwable) {
            continuation.resumeWithException(error)
        }
    }

    private fun withTransport(test: suspend (SilentVpnService, TransportProcess) -> Unit) {
        assumeTrue("Use an isolated emulator", Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue(VpnNetworkHelper.hasAnyUnderlyingInternet(context))
        check(!SilentVpnService.isRunning && !WdttTunnelManager.running.value)
        val service = SilentVpnService().also {
            ContextWrapper::class.java.getDeclaredMethod("attachBaseContext", Context::class.java)
                .apply { isAccessible = true }.invoke(it, context)
        }
        val transport = TransportProcess()
        val excludedBefore = SilentRepository.APP_EXCLUDED_FROM_VPN
        runBlocking(Dispatchers.Main) {
            try {
                WdttTunnelManager.stopAndAwait()
                SilentRepository.APP_EXCLUDED_FROM_VPN = false
                serviceField("isRunning").setBoolean(null, true)
                managerField("overlayRestoreSuppressed").setBoolean(WdttTunnelManager, false)
                managerField("suppressNetworkRecovery").setBoolean(WdttTunnelManager, false)
                managerField("lastOverlayEndedMs").setLong(WdttTunnelManager, 0L)
                managerField("processStartedAtMs").setLong(WdttTunnelManager, System.currentTimeMillis() - 300_000L)
                managerField("lastParams").set(WdttTunnelManager, WdttTunnelManager.Params(
                    "127.0.0.1", 9, emptyList(), "fixture", "fixture",
                ))
                managerField("lastContext").set(WdttTunnelManager, context)
                managerField("process").set(WdttTunnelManager, transport)
                WdttTunnelManager.running.value = true
                WdttTunnelManager.tunnelReady.value = true
                WdttTunnelManager.activeWorkers.value = 12
                test(service, transport)
            } finally {
                SilentVpnService::class.java.getDeclaredMethod("teardownNetworkCallback")
                    .apply { isAccessible = true }.invoke(service)
                // Cancel before the manager's 1.5s delayed native start can execute.
                (serviceField("scope").get(service) as CoroutineScope).cancel()
                serviceField("isRunning").setBoolean(null, false)
                WdttTunnelManager.prepareForShutdown()
                WdttTunnelManager.stopAndAwait()
                SilentRepository.APP_EXCLUDED_FROM_VPN = excludedBefore
            }
        }
    }

    @Test fun validationProbeAloneDoesNotStopAnExistingTransport() = withTransport { service, transport ->
        recover(service, "validated_after_gap")
        assertEquals("A validation probe flag alone killed the live VPN transport", 0, transport.stops())
    }

    @Test fun confirmedNetworkGapDoesNotKeepOldTransportSockets() = withTransport { service, transport ->
        recover(service, "wifi_gap_restored")
        assertTrue("A confirmed lost network kept the original sockets", transport.stops() > 0)
    }

    @Test fun validationEventCannotOverwriteAQueuedRealGap() = withTransport { service, transport ->
        val schedule = SilentVpnService::class.java.getDeclaredMethod(
            "scheduleNetworkRecovery", String::class.java, java.lang.Long.TYPE,
        ).apply { isAccessible = true }
        schedule.invoke(service, "wifi_gap_restored", 200L)
        schedule.invoke(service, "validated_after_gap", 400L)
        withTimeout(4_000) { while (transport.stops() == 0) delay(50) }
        assertEquals(1, transport.stops())
    }

    @Test fun silentGapWithUnchangedAndroidNetworkRestartsAfterFailedDataProbes() = withTransport { service, transport ->
        withPathServer(false) {
            seedOutstandingTraffic(service)
            checkPath(service)
            withTimeout(6_000) { while (transport.stops() == 0) delay(50) }
            assertEquals(1, transport.stops())
        }
    }

    @Test fun backendErrorOverLiveTunnelDoesNotRestartTransport() = withTransport { service, transport ->
        withPathServer(true) {
            seedOutstandingTraffic(service)
            checkPath(service)
            delay(250)
            assertEquals("An upstream HTTP error is proof of a working tunnel", 0, transport.stops())
        }
    }

    @Test fun manualStopCancelsPendingTransportRestart() = withTransport { service, transport ->
        recover(service, "cell_gap_restored")
        assertEquals(1, transport.stops())
        WdttTunnelManager.prepareForShutdown()
        WdttTunnelManager.stopAndAwait()
        delay(1_800)
        assertEquals(null, managerField("lastParams").get(WdttTunnelManager))
        assertEquals(null, managerField("process").get(WdttTunnelManager))
    }

    @Test fun retiredNetworkCallbackCannotChangeTheReplacementSession() = withTransport { service, _ ->
        SilentVpnService::class.java.getDeclaredMethod("setupNetworkCallback")
            .apply { isAccessible = true }.invoke(service)
        delay(100)
        val callback = serviceField("networkCallback").get(service) as ConnectivityManager.NetworkCallback
        val selected = serviceField("selectedUnderlying").get(service) as android.net.Network
        val epoch = serviceField("disconnectEpoch")
        epoch.setInt(service, epoch.getInt(service) + 1)
        SilentVpnService::class.java.getDeclaredMethod("setupNetworkCallback")
            .apply { isAccessible = true }.invoke(service)
        assertNotSame("A replacement session kept a retired callback", callback, serviceField("networkCallback").get(service))
        serviceField("lastBlackoutAtMs").setLong(service, 0)
        callback.onLost(selected)
        delay(100)
        assertEquals("A retired callback mutated the replacement session", 0L, serviceField("lastBlackoutAtMs").getLong(service))
    }

    private fun seedOutstandingTraffic(service: SilentVpnService) {
        val watch = serviceField("dataWatch").get(service) as TunnelDataWatch
        val now = SystemClock.elapsedRealtime()
        watch.observe(TunnelDataWatch.Sample(10, 10), now - 16_000)
        watch.observe(TunnelDataWatch.Sample(11, 10), now - 15_000)
    }

    private suspend fun checkPath(service: SilentVpnService) {
        SilentVpnService::class.java.getDeclaredMethod("checkTunnelDataPath")
            .apply { isAccessible = true }.invoke(service)
        (serviceField("dataCheckJob").get(service) as? Job)?.join()
    }

    private suspend fun withPathServer(upstreamResponds: Boolean, test: suspend () -> Unit) {
        val processField = BrowserScopedTunnel::class.java.getDeclaredField("process").apply { isAccessible = true }
        val previous = processField.get(BrowserScopedTunnel)
        val server = ServerSocket(18766, 8, InetAddress.getByName("127.0.0.1"))
        processField.set(BrowserScopedTunnel, TransportProcess())
        val worker = thread(isDaemon = true, name = "path-probe-fixture") {
            runCatching {
                while (!server.isClosed) server.accept().use { client ->
                    val reader = client.getInputStream().bufferedReader()
                    val request = reader.readLine().orEmpty()
                    while (!reader.readLine().isNullOrEmpty()) { }
                    val health = request.contains("/_silent/health")
                    val body = if (health) "{\"sent\":14,\"received\":10}" else ""
                    val marker = if (!health && upstreamResponds) "X-Silent-Upstream: 1\r\n" else ""
                    val status = if (health) 200 else 502
                    client.getOutputStream().write("HTTP/1.1 $status Result\r\n${marker}Content-Length: ${body.length}\r\nConnection: close\r\n\r\n$body".toByteArray())
                }
            }
        }
        try { test() } finally {
            server.close()
            worker.join(1_000)
            processField.set(BrowserScopedTunnel, previous)
        }
    }
}
