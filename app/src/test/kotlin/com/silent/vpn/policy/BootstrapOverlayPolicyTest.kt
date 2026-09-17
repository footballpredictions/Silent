package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BootstrapOverlayPolicyTest {

    @Test
    fun `temp vpn for mail uses a live cell not flapping hive udp`() {
        val got = BootstrapOverlayPolicy.pick(
            hiveIp = "132.243.234.162",
            hivePort = 56000,
            cellIps = listOf("87.58.213.193", "78.17.74.27"),
        )
        assertEquals("87.58.213.193", got.ip)
        assertEquals(56000, got.port)
        assertFalse(got.isHive)
    }

    @Test
    fun `without cells overlay stays on hive`() {
        val got = BootstrapOverlayPolicy.pick(
            hiveIp = "132.243.234.162",
            hivePort = 56000,
            cellIps = emptyList(),
        )
        assertEquals("132.243.234.162", got.ip)
        assertTrue(got.isHive)
    }

    @Test
    fun `standby api urls yield cell ips and skip hive and ai cell`() {
        val ips = BootstrapOverlayPolicy.cellIpsFromUrls(
            listOf(
                "http://87.58.213.193:9100",
                "https://132-243-234-162.nip.io:2083",
                "https://132.243.234.162:2083",
                "http://78.17.74.27:9100",
                "http://192.177.26.38:9100",
            ),
            hiveIps = setOf("132.243.234.162", "132-243-234-162.nip.io"),
        )
        assertEquals(listOf("87.58.213.193", "78.17.74.27"), ips)
    }
}
