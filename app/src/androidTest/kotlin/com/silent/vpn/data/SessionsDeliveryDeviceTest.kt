package com.silent.vpn.data

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.BrowserScopedTunnel
import com.silent.vpn.vpn.WdttTunnelManager
import java.net.ServerSocket
import java.net.InetAddress
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.concurrent.thread
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real Retrofit/OkHttp against the native relay boundary; disposable emulator only. */
@RunWith(AndroidJUnit4::class)
class SessionsDeliveryDeviceTest {
    @Test fun sessionsUseRelayWithWhitelistAndRefreshWithoutOverlayOrBaseMutation() = runBlocking {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = SilentPrefs.open(context)
        val oldPrefs = prefs.all.toMap()
        val processField = BrowserScopedTunnel::class.java.getDeclaredField("process").apply { isAccessible = true }
        val runningField = SilentVpnService::class.java.getDeclaredField("isRunning").apply { isAccessible = true }
        val oldProcess = processField.get(BrowserScopedTunnel)
        assumeTrue(oldProcess == null && !SilentVpnService.isRunning && !WdttTunnelManager.running.value)
        val oldReady = WdttTunnelManager.tunnelReady.value
        val process = ProcessBuilder("/system/bin/sleep", "120").start()
        val requests = CopyOnWriteArrayList<String>()
        val marker = java.util.concurrent.atomic.AtomicBoolean(true)
        val logoutDuringRefresh = java.util.concurrent.atomic.AtomicBoolean(false)
        var name = "Other phone"
        var deleted = false
        val server = ServerSocket(18766, 10, InetAddress.getByName("127.0.0.1"))
        val worker = thread(isDaemon = true) {
            try {
                while (!server.isClosed) server.accept().use { socket ->
                    socket.soTimeout = 5000
                    val input = socket.getInputStream().buffered()
                    val header = StringBuilder()
                    while (!header.endsWith("\r\n\r\n")) {
                        val value = input.read()
                        if (value < 0) error("Incomplete HTTP header")
                        header.append(value.toChar())
                    }
                    val lines = header.toString().split("\r\n")
                    val request = lines.first().split(' ')
                    val length = lines.firstOrNull { it.startsWith("Content-Length:", true) }?.substringAfter(':')?.trim()?.toInt() ?: 0
                    val bytes = ByteArray(length)
                    var offset = 0
                    while (offset < length) { val n = input.read(bytes, offset, length - offset); if (n < 0) error("Incomplete body"); offset += n }
                    requests.add(request.take(2).joinToString(" "))
                    val auth = lines.firstOrNull { it.startsWith("Authorization:", true) }.orEmpty()
                    var status = 200
                    val response = when {
                        request[1] == "/api/auth/refresh" -> {
                            check(JSONObject(bytes.toString(Charsets.UTF_8)).getString("refresh_token") == "fixture-refresh")
                            if (logoutDuringRefresh.get()) prefs.edit().remove("access_token").remove("refresh_token").commit()
                            """{"access_token":"fixture-new","refresh_token":"fixture-refresh"}"""
                        }
                        !auth.endsWith("Bearer fixture-new") -> { status = 401; """{"detail":"expired"}""" }
                        request[0] == "PATCH" -> { name = JSONObject(bytes.toString(Charsets.UTF_8)).getString("device_name"); "{}" }
                        request[0] == "DELETE" -> { deleted = true; "{}" }
                        else -> """{"id":"user","email":"fixture@example.test","display_id":"42","is_admin":false,"subscription":{"is_active":true,"days_left":10},"max_devices":3,"devices_count":${if (deleted) 0 else 1},"devices":${if (deleted) "[]" else "[{\"id\":\"other\",\"device_name\":${JSONObject.quote(name)},\"device_type\":\"android\",\"is_connected\":true}]"}}"""
                    }.toByteArray()
                    val headers = "HTTP/1.1 $status OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: ${response.size}\r\n${if (marker.get()) "X-Silent-Upstream: 1\r\n" else ""}\r\n"
                    socket.getOutputStream().apply { write(headers.toByteArray()); write(response); flush() }
                }
            } catch (_: Exception) { /* Closing the fixture stops accept. Assertions also verify all replies. */ }
        }
        try {
            prefs.edit().clear().putString("server_url", "http://127.0.0.1:9").commit()
            val repo = SilentRepository(context)
            repo.saveTokens("fixture-old", "fixture-refresh")
            repo.saveExcludedApps(setOf("com.android.settings"), true)
            repo.saveSitesWhitelist(true)
            val originalBase = repo.getServerUrl()
            processField.set(BrowserScopedTunnel, process)
            runningField.setBoolean(null, true)
            WdttTunnelManager.running.value = true
            WdttTunnelManager.tunnelReady.value = true
            assertTrue(repo.isMainVpnTunnelUp())
            val profile = repo.fetchSessionsProfileLive().getOrThrow()
            assertEquals("other", profile.devices.single().id)
            assertTrue(profile.devices.single().is_connected)
            assertTrue(repo.renameSession("other", "TV renamed").isSuccessful)
            assertEquals("TV renamed", repo.fetchSessionsProfileLive().getOrThrow().devices.single().device_name)
            assertTrue(repo.deleteSession("other").isSuccessful)
            assertTrue(repo.fetchSessionsProfileLive().getOrThrow().devices.isEmpty())
            assertEquals(originalBase, repo.getServerUrl())
            assertSame(process, processField.get(BrowserScopedTunnel))
            assertFalse(WdttTunnelManager.isApiOverlayActive())
            assertTrue(requests.contains("POST /api/auth/refresh"))
            assertTrue(requests.all { it.substringAfter(' ') in setOf("/api/users/me", "/api/users/devices/other", "/api/auth/refresh") })
            marker.set(false)
            assertTrue("A local response is not proof of upstream delivery", repo.fetchSessionsProfileLive().isFailure)
            marker.set(true)
            repo.saveTokens("fixture-old", "fixture-refresh")
            logoutDuringRefresh.set(true)
            assertTrue(repo.fetchSessionsProfileLive().isFailure)
            assertNull("A delayed refresh restored an explicitly closed login", repo.getAccessToken())
            assertNull(repo.getRefreshToken())
        } finally {
            WdttTunnelManager.running.value = false
            WdttTunnelManager.tunnelReady.value = oldReady
            runningField.setBoolean(null, false)
            processField.set(BrowserScopedTunnel, oldProcess)
            process.destroy()
            server.close()
            worker.join(1000)
            prefs.edit().clear().apply {
                oldPrefs.forEach { (key, value) -> when (value) {
                    is String -> putString(key, value)
                    is Boolean -> putBoolean(key, value)
                    is Int -> putInt(key, value)
                    is Long -> putLong(key, value)
                    is Float -> putFloat(key, value)
                    is Set<*> -> putStringSet(key, value.filterIsInstance<String>().toSet())
                } }
            }.commit()
        }
    }
}
