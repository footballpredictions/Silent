package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SiteBypassRoutesTest {

    @Test
    fun `site whitelist includes only selected networks and service routes`() {
        val allowed = AllowedIpsHelper.siteWhitelistAllowedIPs(
            listOf("8.8.8.8/32", "192.168.0.0/16"), emptyList(), listOf("1.1.1.1"),
        ).split(", ")
        assertEquals(setOf("8.8.8.8/32", "192.168.0.0/16", "10.66.66.0/24", "1.1.1.1/32"), allowed.toSet())
        assertTrue("0.0.0.0/0" !in allowed)
    }

    @Test
    fun `empty site whitelist retains API and DNS without full tunnel fallback`() {
        assertEquals(
            "10.66.66.0/24, 1.1.1.1/32",
            AllowedIpsHelper.siteWhitelistAllowedIPs(emptyList(), emptyList(), listOf("1.1.1.1")),
        )
    }

    @Test
    fun `site whitelist cannot pull TURN endpoint into tunnel`() {
        val allowed = AllowedIpsHelper.siteWhitelistAllowedIPs(
            listOf("8.8.8.8/32", "192.168.0.0/16"), listOf("8.8.8.8"), emptyList(),
        )
        assertEquals("192.168.0.0/16, 10.66.66.0/24", allowed)
    }

    @Test
    fun `site whitelist subtracts transport subnet inside a selected subnet`() {
        val allowed = AllowedIpsHelper.siteWhitelistAllowedIPs(
            listOf("192.168.0.0/16"), listOf("192.168.0.0/17"), emptyList(),
        )
        assertEquals("192.168.128.0/17, 10.66.66.0/24", allowed)
    }

    @Test
    fun `normalize strips url and path`() {
        assertEquals("ozon.ru", SiteBypassRoutes.normalizeRuleInput("https://ozon.ru/product/1"))
        assertEquals("1.2.3.4", SiteBypassRoutes.normalizeRuleInput("1.2.3.4"))
        assertEquals("10.0.0.0/8", SiteBypassRoutes.normalizeRuleInput("10.0.0.0/8"))
    }

    @Test
    fun `extractRulesFromImportContent reads json rules array`() {
        val content = """{"version":1,"rules":["ozon.ru","https://whoer.net/ru","1.2.3.4"]}"""
        val rules = SiteBypassRoutes.extractRulesFromImportContent(content)
        assertTrue(rules.contains("ozon.ru"))
        assertTrue(rules.contains("whoer.net"))
        assertTrue(rules.contains("1.2.3.4"))
        assertEquals(3, rules.size)
    }

    @Test
    fun `extractRulesFromImportContent reads plain txt and csv`() {
        val content = """
            # comment
            ozon.ru
            telegram.org, 8.8.8.8
        """.trimIndent()
        val rules = SiteBypassRoutes.extractRulesFromImportContent(content)
        assertTrue(rules.contains("ozon.ru"))
        assertTrue(rules.contains("telegram.org"))
        assertTrue(rules.contains("8.8.8.8"))
    }

    @Test
    fun `mergeImportRules keeps unique and respects limit`() {
        val merged = SiteBypassRoutes.mergeImportRules(
            listOf("ozon.ru"),
            listOf("ozon.ru", "whoer.net", "1.2.3.4"),
        )
        assertEquals(listOf("ozon.ru", "whoer.net", "1.2.3.4"), merged)
    }

    @Test
    fun `AllowedIpsHelper generates multi-cidr complement for one host hole`() {
        // Регресс 2ip.io: complement одного /32 → десятки CIDR; на OEM сайт blackhole.
        // Main VPN не должен патчить AllowedIPs этим списком (только excludeRoute).
        val allowed = AllowedIpsHelper.generateExclusionAllowedIPs(listOf("188.40.167.81"))
        val parts = allowed.split(',').map { it.trim() }.filter { it.isNotEmpty() }
        assertTrue("ожидалось много префиксов, got ${parts.size}: $allowed", parts.size > 8)
        assertTrue(parts.none { it == "0.0.0.0/0" })
    }
}
