package com.silent.vpn.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class DnsPresetTest {

    @Test
    fun `default preset keeps server dns`() {
        assertEquals(DnsPreset.SERVER, DnsPreset.DEFAULT)
        assertNull(DnsSettings.override(DnsPreset.SERVER, "1.1.1.1"))
    }

    @Test
    fun `unknown id falls back to default`() {
        assertEquals(DnsPreset.DEFAULT, DnsPreset.fromId(null))
        assertEquals(DnsPreset.DEFAULT, DnsPreset.fromId("doh-something"))
        assertEquals(DnsPreset.SERVER, DnsPreset.fromId("cloudflare"))
        assertEquals(DnsPreset.SERVER, DnsPreset.fromId("yandex"))
        assertEquals(DnsPreset.CUSTOM, DnsPreset.fromId("custom"))
    }

    @Test
    fun `server preset keeps backend dns`() {
        assertNull(DnsSettings.override(DnsPreset.SERVER, ""))
    }

    @Test
    fun `custom servers accept ipv4 and ipv6`() {
        assertEquals("1.1.1.1", DnsPreset.sanitizeCustomServers("1.1.1.1"))
        assertEquals("1.1.1.1, 8.8.8.8", DnsPreset.sanitizeCustomServers("1.1.1.1, 8.8.8.8"))
        assertEquals("1.1.1.1, 8.8.8.8", DnsPreset.sanitizeCustomServers(" 1.1.1.1 ; 8.8.8.8 "))
        assertEquals("2606:4700:4700::1111", DnsPreset.sanitizeCustomServers("2606:4700:4700::1111"))
    }

    @Test
    fun `custom servers reject garbage`() {
        assertNull(DnsPreset.sanitizeCustomServers(""))
        assertNull(DnsPreset.sanitizeCustomServers("   "))
        assertNull(DnsPreset.sanitizeCustomServers("dns.google"))
        assertNull(DnsPreset.sanitizeCustomServers("999.1.1.1"))
        assertNull(DnsPreset.sanitizeCustomServers("1.1.1"))
        assertNull(DnsPreset.sanitizeCustomServers("1.1.1.1/24"))
    }

    @Test
    fun `custom servers drop invalid tokens and duplicates`() {
        assertEquals("1.1.1.1, 9.9.9.9", DnsPreset.sanitizeCustomServers("1.1.1.1, nope, 1.1.1.1, 9.9.9.9"))
    }

    @Test
    fun `custom servers are capped`() {
        val raw = "1.1.1.1, 8.8.8.8, 9.9.9.9, 77.88.8.8"
        val sanitized = DnsPreset.sanitizeCustomServers(raw)
        assertEquals(DnsPreset.MAX_CUSTOM_SERVERS, sanitized?.split(",")?.size)
    }

    @Test
    fun `custom preset without valid input does not override`() {
        assertNull(DnsSettings.override(DnsPreset.CUSTOM, "dns.google"))
        assertEquals("1.1.1.1", DnsSettings.override(DnsPreset.CUSTOM, "1.1.1.1"))
    }

    @Test
    fun `labels describe current choice`() {
        assertEquals("Как на сервере", DnsSettings.describe(DnsPreset.SERVER, ""))
        assertEquals("Свой: 1.1.1.1", DnsSettings.describe(DnsPreset.CUSTOM, "1.1.1.1"))
        assertEquals("Свой DNS (не задан)", DnsSettings.describe(DnsPreset.CUSTOM, "oops"))
        assertEquals("1.1.1.1", DnsSettings.shortLabel(DnsPreset.CUSTOM, "1.1.1.1"))
    }

    @Test
    fun `only server is selectable`() {
        val selectable = DnsPreset.selectable()
        assertEquals(1, selectable.size)
        assertEquals(DnsPreset.SERVER, selectable.first())
        assertTrue(selectable.none { it == DnsPreset.CUSTOM })
    }
}
