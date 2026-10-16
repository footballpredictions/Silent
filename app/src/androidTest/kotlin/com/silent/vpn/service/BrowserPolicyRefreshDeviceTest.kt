package com.silent.vpn.service

import android.content.Intent
import android.net.VpnService
import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.vpn.*
import com.wireguard.config.Config
import java.io.ByteArrayInputStream
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real native process + TUN, restricted to benchmark IPs on a disposable emulator. */
@RunWith(AndroidJUnit4::class)
class BrowserPolicyRefreshDeviceTest {
    private fun native(): Process = BrowserScopedTunnel::class.java.getDeclaredField("process")
        .apply { isAccessible = true }.get(BrowserScopedTunnel) as Process

    @Test fun backgroundAddressRefreshPreservesWireGuardAndTun() {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        check(!WdttTunnelManager.running.value && !OlcrtcTunnelManager.running.value && !BrowserScopedTunnel.isRunning())
        assertNull("Grant ACTIVATE_VPN only on the disposable emulator", VpnService.prepare(context))
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
        val policy = AppTunnelPolicy(false, setOf(context.packageName))
        val domains = listOf("fixture.example")
        try {
            BrowserScopedTunnel.start(context, config, policy, excluded, listOf("198.18.0.10/32"), domains, false, "first-address")
            val original = native()
            BrowserScopedTunnel.start(context, config, policy, excluded, listOf("198.18.0.20/32"), domains, false, "changed-address")
            assertSame("A DNS address refresh replaced the live WG/TUN", original, native())
            assertTrue(original.isAlive)
            assertNotNull(BrowserScopedTunnel.pathHealth())
        } finally {
            BrowserScopedTunnel.stop()
            context.stopService(Intent(context, BrowserScopedVpnService::class.java))
        }
    }
}
