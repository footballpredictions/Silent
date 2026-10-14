package com.silent.vpn.service

import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.vpn.AllowedIpsHelper
import com.silent.vpn.vpn.AppTunnelPolicy
import com.silent.vpn.vpn.BrowserScopedTunnel
import com.silent.vpn.vpn.Ipv4Cidr
import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.SiteBypassRoutes
import com.silent.vpn.vpn.WdttTunnelManager
import com.wireguard.config.Config
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeFalse
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.ByteArrayInputStream
import java.io.File

/** Actual native lifetime regression; only a disposable emulator may own this synthetic TUN. */
@RunWith(AndroidJUnit4::class)
class BrowserNetworkRebindDeviceTest {
    private fun nativeProcess(): Process? =
        BrowserScopedTunnel::class.java.getDeclaredField("process").apply { isAccessible = true }
            .get(BrowserScopedTunnel) as? Process

    @Test fun sameConfigHandover_replacesNativeSocketsAndKeepsReplacementAlive() {
        assumeTrue("Use an isolated emulator", Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        assumeFalse("Never replace an existing WDTT session", WdttTunnelManager.running.value)
        assumeFalse("Never replace an existing RTC session", OlcrtcTunnelManager.running.value)
        assumeFalse("Never replace an existing browser tunnel", BrowserScopedTunnel.isRunning())
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertNull("Grant ACTIVATE_VPN to the debug package on the disposable emulator first", VpnService.prepare(context))

        // Restrict the Android TUN to the benchmarking range. Public/loopback traffic
        // remains outside it; the fixture has no DNS, account, or production peer.
        val syntheticRange = Ipv4Cidr(0xc6120000L, 15)
        val excluded = SiteBypassRoutes.complementCidrs(listOf(syntheticRange)).map { it.toString() }
        assertEquals("198.18.0.0/15", AllowedIpsHelper.generateExclusionAllowedIPs(excluded))
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
        """.trimIndent().toByteArray(Charsets.UTF_8)))
        val policy = AppTunnelPolicy(false, setOf(context.packageName))
        val semanticKey = "isolated-native-network-rebind-fixture"
        try {
            BrowserScopedTunnel.start(context, config, policy, excluded, emptyList(), emptyList(), false, semanticKey)
            val original = checkNotNull(nativeProcess())
            assertTrue(original.isAlive)

            BrowserScopedTunnel.start(context, config, policy, excluded, emptyList(), emptyList(), false, semanticKey)
            assertSame("Ordinary same-policy updates must preserve the native process", original, nativeProcess())

            // Represents a disruptive network event with an unchanged WG config/site policy.
            BrowserScopedTunnel.start(context, config, policy, excluded, emptyList(), emptyList(), false,
                semanticKey, forceSocketRebind = true)
            val replacement = checkNotNull(nativeProcess())
            assertNotSame("Network recovery reused sockets from the old native process", original, replacement)
            assertFalse("Old native process remained alive after rebind", original.isAlive)
            SystemClock.sleep(500L)
            assertSame("Retiring output reader stopped the replacement", replacement, nativeProcess())
            assertTrue("Replacement native transport stopped unexpectedly", replacement.isAlive)
            assertFalse("Private native runtime config remained on disk",
                File(context.noBackupFilesDir, "browser-routing-runtime.json").exists())
        } finally {
            BrowserScopedTunnel.stop()
            context.stopService(Intent(context, BrowserScopedVpnService::class.java))
        }
    }
}
