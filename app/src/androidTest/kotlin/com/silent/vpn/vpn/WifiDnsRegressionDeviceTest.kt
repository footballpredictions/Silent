package com.silent.vpn.vpn

import android.content.Intent
import android.content.Context
import android.content.ContextWrapper
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.NetworkCapabilities
import android.net.RouteInfo
import android.net.VpnService
import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.SilentApp
import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.RussianServices
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.BrowserScopedVpnService
import java.net.InetAddress
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Actual main-VPN configuration on a disposable Wi-Fi emulator; no account/server. */
@RunWith(AndroidJUnit4::class)
class WifiDnsRegressionDeviceTest {
    private fun checkDns(preset: DnsPreset, expected: String, checkLan: Boolean = false) = runBlocking {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cm = context.getSystemService(ConnectivityManager::class.java)
        assumeTrue(cm.allNetworks.any {
            cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        })
        assertNull("Grant VPN permission only on the disposable emulator", VpnService.prepare(context))
        check(!WdttTunnelManager.running.value && !BrowserScopedTunnel.isRunning())
        val prefs = SilentPrefs.open(context)
        val old = prefs.all.toMap()
        // The suite uses HiltTestApplication; supply the normal backend owner
        // without running the production application's background startup work.
        val app = SilentApp()
        ContextWrapper::class.java.getDeclaredMethod("attachBaseContext", Context::class.java)
            .apply { isAccessible = true }.invoke(app, context)
        val helper = WireGuardHelper(object : ContextWrapper(context) {
            override fun getApplicationContext(): Context = app
        })
        try {
            prefs.edit().clear().putString(SilentRepository.PREF_DNS_PRESET, preset.id)
                .putString(SilentRepository.PREF_DNS_CUSTOM, expected).commit()
            RussianServices.setEnabled(context, false)
            helper.startTunnel("""
                [Interface]
                PrivateKey = AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE=
                Address = 198.18.0.2/32
                DNS = 198.18.0.1
                MTU = 1200

                [Peer]
                PublicKey = AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI=
                AllowedIPs = 0.0.0.0/0
                Endpoint = 127.0.0.1:9
                PersistentKeepalive = 0
            """.trimIndent())
            val deadline = SystemClock.elapsedRealtime() + 3_000
            var actual = emptyList<String>()
            var properties: LinkProperties? = null
            while (SystemClock.elapsedRealtime() < deadline) {
                val network = cm.allNetworks.firstOrNull {
                    cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
                }
                properties = network?.let(cm::getLinkProperties)
                actual = properties?.dnsServers?.mapNotNull { it.hostAddress }.orEmpty()
                if (actual.isNotEmpty()) break
                Thread.sleep(20)
            }
            if (checkLan) {
                val routes = checkNotNull(properties).routes
                fun tunneled(ip: String): Boolean = routes
                    .filter { it.destination.contains(InetAddress.getByName(ip)) }
                    .maxByOrNull { it.destination.prefixLength }?.type == RouteInfo.RTN_UNICAST
                assertFalse("Main TUN captured the home router despite LAN exclusions", tunneled("192.168.1.1"))
                assertTrue("LAN exclusions removed the tunnel API route", tunneled("10.66.66.1"))
            } else {
                assertEquals("Wi-Fi router/gateway replaced the configured VPN DNS", listOf(expected), actual)
            }
        } finally {
            helper.forceStopSilentTunnel()
            context.stopService(Intent(context, BrowserScopedVpnService::class.java))
            val deadline = SystemClock.elapsedRealtime() + 3_000
            while (BrowserScopedVpnService.instance != null && SystemClock.elapsedRealtime() < deadline) Thread.sleep(10)
            assertNull(BrowserScopedVpnService.instance)
            val editor = prefs.edit().clear()
            for ((key, value) in old) when (value) {
                is String -> editor.putString(key, value)
                is Boolean -> editor.putBoolean(key, value)
                is Int -> editor.putInt(key, value)
                is Long -> editor.putLong(key, value)
                is Float -> editor.putFloat(key, value)
                is Set<*> -> @Suppress("UNCHECKED_CAST") editor.putStringSet(key, value as Set<String>)
            }
            editor.commit()
        }
    }

    @Test fun wifiKeepsServerDns() = checkDns(DnsPreset.DEFAULT, "198.18.0.1")
    @Test fun wifiKeepsSelectedDns() = checkDns(DnsPreset.CUSTOM, "1.1.1.1")
    @Test fun wifiLanBypassReachesMainTun() = checkDns(DnsPreset.DEFAULT, "198.18.0.1", checkLan = true)
}
