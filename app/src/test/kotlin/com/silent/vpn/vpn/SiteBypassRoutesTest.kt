package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SiteBypassRoutesTest {

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
