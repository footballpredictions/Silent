package com.silent.vpn.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Парсинг deep link silentvpn://ref?code=… без Android framework
 * (логика совпадает с MainActivity.handleReferralDeepLink).
 */
class ReferralDeepLinkTest {

    private fun extractReferralCode(uriString: String): String? {
        // Minimal parser for silentvpn://ref?code=VALUE
        val prefix = "silentvpn://ref"
        if (!uriString.startsWith(prefix)) return null
        val query = uriString.substringAfter('?', missingDelimiterValue = "")
        if (query.isEmpty()) return null
        for (part in query.split('&')) {
            val key = part.substringBefore('=')
            val raw = part.substringAfter('=', missingDelimiterValue = "")
            if (key == "code") {
                val decoded = java.net.URLDecoder.decode(raw, Charsets.UTF_8)
                return decoded.trim().takeIf { it.isNotBlank() }
            }
        }
        return null
    }

    @Test
    fun parsesCodeFromRefLink() {
        assertEquals("ABCD1234", extractReferralCode("silentvpn://ref?code=ABCD1234"))
    }

    @Test
    fun trimsWhitespace() {
        assertEquals("XYZ9", extractReferralCode("silentvpn://ref?code=%20XYZ9%20"))
    }

    @Test
    fun ignoresVkLinkedHost() {
        assertNull(extractReferralCode("silentvpn://vk-linked?boot=abc&vk=1"))
    }

    @Test
    fun ignoresMissingCode() {
        assertNull(extractReferralCode("silentvpn://ref"))
        assertNull(extractReferralCode("silentvpn://ref?code="))
    }
}
