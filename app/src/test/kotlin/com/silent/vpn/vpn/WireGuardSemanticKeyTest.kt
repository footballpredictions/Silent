package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WireGuardSemanticKeyTest {
    private fun config(routes: String, dns: String = "1.1.1.1") = """
        [Interface]
        PrivateKey = test-private
        Address = 10.66.66.2/32
        DNS = $dns
        [Peer]
        PublicKey = test-public
        AllowedIPs = $routes
        Endpoint = 127.0.0.1:9000
    """.trimIndent()

    @Test
    fun `api only to browser tunnel must invalidate cached config`() {
        val apiOnly = config("10.66.66.0/24, 89.125.188.100/32")
        val browser = config("0.0.0.0/0")
        assertNotEquals(WireGuardSemanticKey.from(apiOnly), WireGuardSemanticKey.from(browser))
    }

    @Test
    fun `late turn credentials promote restricted bootstrap without changing localhost endpoint`() {
        val original = config("0.0.0.0/0")
        val early = AllowedIpsHelper.patchAllowedIPsForBootstrapAuth(original, "89.125.188.100")
        val late = AllowedIpsHelper.patchAllowedIPs(original, listOf("87.240.190.78"))
        assertTrue(early.contains("10.66.66.0/24"))
        assertNotEquals(WireGuardSemanticKey.from(early), WireGuardSemanticKey.from(late))
        assertTrue(late.contains("Endpoint = 127.0.0.1:9000"))
        val routes = late.lineSequence().first { it.startsWith("AllowedIPs") }
            .substringAfter('=')
            .split(',')
            .map { it.trim() }
        fun covers(ip: String): Boolean {
            fun number(s: String) = s.split('.').fold(0L) { n, octet -> (n shl 8) or octet.toLong() }
            val target = number(ip)
            return routes.any {
                val prefix = it.substringAfter('/').toInt()
                val mask = if (prefix == 0) 0L else (0xffffffffL shl (32 - prefix)) and 0xffffffffL
                (target and mask) == (number(it.substringBefore('/')) and mask)
            }
        }
        assertFalse(covers("87.240.190.78")) // TURN stays on the underlying network.
        assertTrue(covers("10.66.66.1")) // API stays in the tunnel.
        assertTrue(covers("203.0.113.42")) // Arbitrary external browser destination.
    }

    @Test
    fun `second and later allowed routes participate in key`() {
        assertNotEquals(
            WireGuardSemanticKey.from(config("0.0.0.0/1, 128.0.0.0/2")),
            WireGuardSemanticKey.from(config("0.0.0.0/1, 192.0.0.0/2")),
        )
    }

    @Test
    fun `same route set reordered is not a reconnect`() {
        assertEquals(
            WireGuardSemanticKey.from(config("10.66.66.0/24, 89.125.188.100/32")),
            WireGuardSemanticKey.from(
                config("89.125.188.100/32,10.66.66.0/24,10.66.66.0/24").replace("\n", "\r\n"),
            ),
        )
    }

    @Test
    fun `dns change must not leave stale resolver`() {
        assertNotEquals(
            WireGuardSemanticKey.from(config("0.0.0.0/0", "1.1.1.1")),
            WireGuardSemanticKey.from(config("0.0.0.0/0", "8.8.8.8")),
        )
    }
}
