package com.silent.vpn.vk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HashParserTest {

    @Test
    fun `extract from full vk call link`() {
        assertEquals(
            "AbCdEf123_-x",
            HashParser.extract("https://vk.com/call/join/AbCdEf123_-x"),
        )
    }

    @Test
    fun `extract strips query and fragment`() {
        assertEquals(
            "AbCdEf123",
            HashParser.extract("https://vk.com/call/join/AbCdEf123?utm=1&x=2"),
        )
        assertEquals(
            "AbCdEf123",
            HashParser.extract("https://vk.com/call/join/AbCdEf123#section"),
        )
    }

    @Test
    fun `extract handles trailing slash and whitespace`() {
        assertEquals(
            "AbCdEf123",
            HashParser.extract("  https://vk.com/call/join/AbCdEf123/  "),
        )
    }

    @Test
    fun `extract bare token`() {
        assertEquals("AbCdEf123_-x", HashParser.extract("AbCdEf123_-x"))
    }

    @Test
    fun `extract bare token with scheme and www`() {
        assertEquals("AbCdEf123456", HashParser.extract("https://www.AbCdEf123456"))
    }

    @Test
    fun `extract rejects garbage`() {
        assertNull(HashParser.extract(""))
        assertNull(HashParser.extract("   "))
        assertNull(HashParser.extract("short"))
        assertNull(HashParser.extract("has spaces inside token"))
        assertNull(HashParser.extract("https://vk.com/some/other/page!"))
    }

    @Test
    fun `extract rejects token longer than 128`() {
        assertNull(HashParser.extract("a".repeat(129)))
    }

    @Test
    fun `normalizeList dedupes and drops invalid`() {
        val input = listOf(
            "https://vk.com/call/join/AbCdEf123",
            "AbCdEf123",
            "bad token",
            "https://vk.com/call/join/Zz9999xx",
        )
        assertEquals(
            listOf("AbCdEf123", "Zz9999xx"),
            HashParser.normalizeList(input),
        )
    }
}
