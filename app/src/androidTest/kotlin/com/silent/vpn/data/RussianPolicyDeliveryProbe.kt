package com.silent.vpn.data

import android.os.Build
import android.content.Intent
import android.net.VpnService
import com.silent.vpn.service.BrowserScopedVpnService
import com.silent.vpn.vpn.*
import com.wireguard.config.Config
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.net.URLConnection
import java.net.URLStreamHandler
import java.util.concurrent.CopyOnWriteArrayList
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in disposable-emulator probe. Intercepts only this test process's URL API;
 * models blocked public control-plane endpoints and an available VPN API relay.
 * Run separately: its URL factory intentionally lives until the process exits.
 */
@RunWith(AndroidJUnit4::class)
class RussianPolicyDeliveryProbe {
    @Test fun blockedPublicEndpointsMustNotLeavePolicyStaleWhenVpnRelayIsAvailable() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("policyDeliveryProbe") == "true")
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        check(!WdttTunnelManager.running.value && !OlcrtcTunnelManager.running.value && !BrowserScopedTunnel.isRunning())
        assertNull("Only the owned emulator may grant VPN access", VpnService.prepare(context))
        val prefs = SilentPrefs.open(context)
        val key = "russian_routing_policy_v1"
        val before = prefs.getString(key, null)
        val enabled = RussianServices.enabled(context)
        val attempted = RussianServices::class.java.getDeclaredField("attemptedAt").apply { isAccessible = true }
        val beforeAttempt = attempted.getLong(RussianServices)
        fun policy(revision: String, direct: List<String>, vpn: List<String>) = JSONObject()
            .put("schema_version", 1).put("revision", revision.repeat(64))
            .put("direct_domains", JSONArray(direct)).put("vpn_domains", JSONArray(vpn))
        val old = policy("a", listOf("ru", "flashscore.com"), listOf("gdz-raketa.ru"))
        val fresh = policy("b", listOf("ru"), listOf("gdz.ru", "flashscore.com"))
        val requests = CopyOnWriteArrayList<String>()
        var responseBody = fresh.toString()
        var relayAvailable = true
        var disableDuringRead = false
        fun connection(url: URL): HttpURLConnection = object : HttpURLConnection(url) {
            override fun connect() {}
            override fun disconnect() {}
            override fun usingProxy() = false
            override fun getResponseCode(): Int {
                requests.add(url.toString())
                if (relayAvailable && url.host == "127.0.0.1" && url.port == 18766 && url.path == "/api/vpn/routing-policy") return 200
                throw IOException("Public endpoint blocked by mobile whitelist fixture")
            }
            override fun getInputStream(): ByteArrayInputStream {
                if (disableDuringRead) RussianServices.setEnabled(context, false)
                return ByteArrayInputStream(responseBody.toByteArray())
            }
            override fun getHeaderField(name: String): String? = if (name == "X-Silent-Upstream") "1" else null
        }
        URL.setURLStreamHandlerFactory { scheme ->
            if (scheme == "http" || scheme == "https") object : URLStreamHandler() {
                override fun openConnection(url: URL): URLConnection = connection(url)
                override fun openConnection(url: URL, proxy: Proxy): URLConnection = connection(url)
            } else null
        }
        try {
            val config = Config.parse(ByteArrayInputStream("""
                [Interface]
                PrivateKey = AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=
                Address = 198.18.0.2/32
                MTU = 1200

                [Peer]
                PublicKey = AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=
                AllowedIPs = 198.18.0.0/15
                Endpoint = 127.0.0.1:9
                PersistentKeepalive = 0
            """.trimIndent().toByteArray()))
            val excluded = SiteBypassRoutes.complementCidrs(listOf(Ipv4Cidr(0xc6120000L, 15))).map { it.toString() }
            BrowserScopedTunnel.start(context, config, AppTunnelPolicy(false, setOf(context.packageName)),
                excluded, emptyList(), emptyList(), false, "policy-delivery-fixture")
            val processField = BrowserScopedTunnel::class.java.getDeclaredField("process").apply { isAccessible = true }
            val originalProcess = processField.get(BrowserScopedTunnel)
            prefs.edit().putString(key, old.toString()).commit()
            RussianServices.setEnabled(context, true)
            attempted.setLong(RussianServices, 0L)
            val changed = RussianServices.refresh(context)
            assertTrue("Cached policy stayed stale although VPN relay is available. Requests: $requests", changed)
            assertEquals(fresh.getString("revision"), RussianServices.config(context).getString("revision"))
            assertEquals("Download alone must not report successful application", RussianServices.Delivery.LOADING, RussianServices.delivery.value)
            assertTrue("Native policy application was not acknowledged", BrowserScopedTunnel.applyRussianPolicy(context))
            assertSame("Policy delivery replaced the main native WG/TUN", originalProcess, processField.get(BrowserScopedTunnel))
            assertEquals(RussianServices.Delivery.RECEIVED, RussianServices.delivery.value)

            // A successful same-revision response differs from failed fetch.
            attempted.setLong(RussianServices, 0L)
            assertFalse(RussianServices.refresh(context))
            assertTrue(RussianServices.hasReceivedPolicy())
            assertTrue(BrowserScopedTunnel.applyRussianPolicy(context))
            assertEquals(RussianServices.Delivery.RECEIVED, RussianServices.delivery.value)

            relayAvailable = false
            attempted.setLong(RussianServices, 0L)
            assertFalse(RussianServices.refresh(context))
            assertFalse(RussianServices.hasReceivedPolicy())
            assertEquals(RussianServices.Delivery.FAILED, RussianServices.delivery.value)
            assertEquals(fresh.getString("revision"), RussianServices.config(context).getString("revision"))

            relayAvailable = true
            responseBody = "{\"schema_version\":9}"
            attempted.setLong(RussianServices, 0L)
            assertFalse(RussianServices.refresh(context))
            assertEquals(RussianServices.Delivery.FAILED, RussianServices.delivery.value)
            assertEquals(fresh.getString("revision"), RussianServices.config(context).getString("revision"))

            // A late response must not re-enable or replace policy after OFF.
            responseBody = policy("c", listOf("ru"), emptyList()).toString()
            disableDuringRead = true
            attempted.setLong(RussianServices, 0L)
            assertFalse(RussianServices.refresh(context))
            assertFalse(RussianServices.enabled(context))
            assertEquals(fresh.getString("revision"), RussianServices.config(context).getString("revision"))
            assertEquals(RussianServices.Delivery.WAITING, RussianServices.delivery.value)
            assertTrue("Policy requests escaped the existing VPN relay: $requests", requests.all { it.startsWith("http://127.0.0.1:18766/") })
        } finally {
            BrowserScopedTunnel.stop()
            context.stopService(Intent(context, BrowserScopedVpnService::class.java))
            prefs.edit().putString(key, before).commit()
            RussianServices.setEnabled(context, enabled)
            attempted.setLong(RussianServices, beforeAttempt)
        }
    }
}
