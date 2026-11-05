package com.silent.vpn.data

import android.os.Build
import android.os.ParcelFileDescriptor
import android.content.Intent
import android.net.VpnService
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.vpn.resolveAppTunnelPolicy
import com.silent.vpn.vpn.resolveBootstrapExcludedApps
import com.silent.vpn.vpn.BrowserScopedTunnel
import com.silent.vpn.vpn.Ipv4Cidr
import com.silent.vpn.vpn.SiteBypassRoutes
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.service.BrowserScopedVpnService
import com.wireguard.config.Config
import java.io.ByteArrayInputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Exercises the production resolver and saved preferences on a disposable emulator. */
@RunWith(AndroidJUnit4::class)
class CombinedAppRoutingDeviceTest {
    private fun withSavedPreferences(test: (android.content.Context, SilentRepository) -> Unit) {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = SilentPrefs.open(context)
        val saved = prefs.all
        try {
            prefs.edit().clear().commit()
            test(context, SilentRepository(context))
        } finally {
            RussianServices.setEnabled(context, false)
            val editor = prefs.edit().clear()
            for ((key, value) in saved) {
                when (value) {
                    is String -> editor.putString(key, value)
                    is Boolean -> editor.putBoolean(key, value)
                    is Int -> editor.putInt(key, value)
                    is Long -> editor.putLong(key, value)
                    is Float -> editor.putFloat(key, value)
                    is Set<*> -> editor.putStringSet(key, value.filterIsInstance<String>().toSet())
                }
            }
            check(editor.commit())
        }
    }

    @Test fun russianBypassKeepsManualBlacklistAtProductionResolver() = withSavedPreferences { context, repo ->
        repo.saveExcludedApps(setOf("com.android.settings"), false)
        val before = resolveAppTunnelPolicy(context)
        val bootstrap = resolveBootstrapExcludedApps(context)
        val overlay = resolveAppTunnelPolicy(context, includeAppInTunnel = true)
        assertTrue("Control: selected installed app must bypass VPN", "com.android.settings" in before.packages)
        repeat(10) {
            RussianServices.setEnabled(context, true)
            val active = resolveAppTunnelPolicy(context)
            assertTrue("RU ON must preserve the selected app's Android VPN exclusion", "com.android.settings" in active.packages)
            assertTrue(active.packages.containsAll(before.packages))
            assertEquals(bootstrap, resolveBootstrapExcludedApps(context))
            assertEquals(overlay, resolveAppTunnelPolicy(context, includeAppInTunnel = true))
            RussianServices.setEnabled(context, false)
            assertEquals(before, resolveAppTunnelPolicy(context))
        }
    }

    @Test fun russianBypassKeepsManualWhitelistAtProductionResolver() = withSavedPreferences { context, repo ->
        repo.saveExcludedApps(setOf("com.android.settings"), true)
        val before = resolveAppTunnelPolicy(context)
        assertTrue("Control: saved whitelist mode must be active", before.whitelist)
        repeat(10) {
            RussianServices.setEnabled(context, true)
            val active = resolveAppTunnelPolicy(context)
            assertTrue("RU ON must preserve the saved whitelist's Android VPN policy", active.whitelist)
            assertTrue(active.packages.containsAll(before.packages))
            assertEquals(setOf("com.android.settings"), SilentRepository(context).getWhitelistPackages())
            RussianServices.setEnabled(context, false)
            assertEquals(before, resolveAppTunnelPolicy(context))
        }
    }

    @Test fun liveVpnKeepsExcludedUidAcrossRussianToggleRefreshAndRestart() = withSavedPreferences { context, repo ->
        assertFalse(WdttTunnelManager.running.value)
        assertFalse(BrowserScopedTunnel.isRunning())
        assertNull("Grant VPN permission only on the disposable emulator", VpnService.prepare(context))
        repo.saveExcludedApps(setOf("com.android.settings"), false)
        val uid = context.packageManager.getApplicationInfo("com.android.settings", 0).uid
        // Benchmark-only routes and a local discard endpoint cannot affect live servers.
        val excluded = SiteBypassRoutes.complementCidrs(listOf(Ipv4Cidr(0xc6120000L, 15))).map { it.toString() }
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
        fun native() = BrowserScopedTunnel::class.java.getDeclaredField("process")
            .apply { isAccessible = true }.get(BrowserScopedTunnel)
        fun assertExcluded() {
            var vpn: String? = null
            val deadline = android.os.SystemClock.elapsedRealtime() + 3_000L
            while (vpn == null && android.os.SystemClock.elapsedRealtime() < deadline) {
                val descriptor = InstrumentationRegistry.getInstrumentation().uiAutomation
                    .executeShellCommand("dumpsys connectivity")
                val snapshot = ParcelFileDescriptor.AutoCloseInputStream(descriptor).bufferedReader().use { it.readText() }
                vpn = snapshot.lineSequence().singleOrNull {
                    "NetworkAgentInfo{" in it && "VPN" in it && "OwnerUid: ${context.applicationInfo.uid}" in it
                }
                if (vpn == null) Thread.sleep(25)
            }
            val record = checkNotNull(vpn) { "No Android VPN network registered for the owned test UID" }
            val ranges = checkNotNull(Regex("Uids: <\\{([^}]+)\\}>").find(record)).groupValues[1]
            val covered = Regex("(\\d+)(?:-(\\d+))?").findAll(ranges).any {
                val first = it.groupValues[1].toInt()
                val last = it.groupValues[2].toIntOrNull() ?: first
                uid in first..last
            }
            assertFalse("Excluded app UID was reintroduced into the live Android VPN", covered)
        }
        try {
            for ((index, enabled) in listOf(false, true, false, true).withIndex()) {
                RussianServices.setEnabled(context, enabled)
                BrowserScopedTunnel.start(context, config, resolveAppTunnelPolicy(context), excluded,
                    emptyList(), emptyList(), false, "combined-toggle-$index", RussianServices.config(context))
                assertExcluded()
                val original = native()
                assertTrue(BrowserScopedTunnel.applyRussianPolicy(context))
                assertSame("Policy refresh must preserve the existing native VPN", original, native())
                assertExcluded()
            }
            BrowserScopedTunnel.stop()
            BrowserScopedTunnel.start(context, config, resolveAppTunnelPolicy(context), excluded,
                emptyList(), emptyList(), false, "combined-restart", RussianServices.config(context))
            assertExcluded()
        } finally {
            BrowserScopedTunnel.stop()
            context.stopService(Intent(context, BrowserScopedVpnService::class.java))
            val deadline = android.os.SystemClock.elapsedRealtime() + 3_000L
            while (BrowserScopedVpnService.instance != null && android.os.SystemClock.elapsedRealtime() < deadline) {
                Thread.sleep(10)
            }
            assertNull(BrowserScopedVpnService.instance)
        }
    }
}
