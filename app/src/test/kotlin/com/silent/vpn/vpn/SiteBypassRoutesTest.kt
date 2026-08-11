package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SiteBypassRoutesTest {

    @Test
    fun `normalize strips url and path`() {
        assertEquals("ozon.ru", SiteBypassRoutes.normalizeRuleInput("https://ozon.ru/product/1"))
        assertEquals("whoer.net", SiteBypassRoutes.normalizeRuleInput("https://whoer.net/ru"))
        assertEquals("1.2.3.4", SiteBypassRoutes.normalizeRuleInput("1.2.3.4"))
        assertEquals("10.0.0.0/8", SiteBypassRoutes.normalizeRuleInput("10.0.0.0/8"))
    }

    @Test
    fun `parseRules skips comments and empties`() {
        val rules = SiteBypassRoutes.parseRules(
            """
            # comment
            ozon.ru
            1.2.3.4
            ozon.ru
            """.trimIndent(),
        )
        assertEquals(listOf("ozon.ru", "1.2.3.4"), rules)
    }

    @Test
    fun `complement single host leaves neighbours`() {
        val hole = Ipv4Cidr(
            (1L shl 24) or (2L shl 16) or (3L shl 8) or 4L,
            32,
        )
        val allowed = SiteBypassRoutes.complementCidrs(listOf(hole))
        val str = allowed.joinToString(", ") { it.toString() }
        assertFalse(covers(str.split(", "), "1.2.3.4"))
        assertTrue(covers(str.split(", "), "1.2.3.5"))
        assertTrue(covers(str.split(", "), "8.8.8.8"))
    }

    @Test
    fun `generateExclusionAllowedIPs accepts cidr holes`() {
        val cidrs = AllowedIpsHelper.generateExclusionAllowedIPs(listOf("10.0.0.0/8")).split(", ")
        assertFalse(covers(cidrs, "10.1.2.3"))
        assertTrue(covers(cidrs, "8.8.8.8"))
    }

    private fun covers(cidrs: List<String>, ip: String): Boolean {
        val target = ip.split('.').fold(0L) { acc, o -> (acc shl 8) or (o.toLong() and 0xFF) }
        return cidrs.any { cidr ->
            val (net, prefix) = cidr.trim().split('/')
            val p = prefix.toInt()
            val mask = if (p == 0) 0L else (0xFFFFFFFFL shl (32 - p)) and 0xFFFFFFFFL
            val n = net.split('.').fold(0L) { acc, o -> (acc shl 8) or (o.toLong() and 0xFF) }
            (target and mask) == (n and mask)
        }
    }
}
