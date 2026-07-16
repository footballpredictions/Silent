package com.silent.vpn.security

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

/**
 * Юнит-тесты anti-tamper логики (без Context / BuildConfig).
 * Запуск: ./gradlew :app:testDebugUnitTest --tests com.silent.vpn.security.IntegrityCryptoTest
 */
class IntegrityCryptoTest {

    @Test
    fun `sha256Hex known vector empty`() {
        // SHA-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assertEquals(
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            IntegrityCrypto.sha256Hex(ByteArray(0)),
        )
    }

    @Test
    fun `sha256Hex known vector abc`() {
        assertEquals(
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            IntegrityCrypto.sha256Hex("abc".toByteArray(Charsets.US_ASCII)),
        )
    }

    @Test
    fun `sha256Hex file matches bytes`() {
        val dir = Files.createTempDirectory("silent-integrity-").toFile()
        val f = File(dir, "libclient.so")
        f.writeBytes("silent-libclient-test".toByteArray())
        try {
            assertEquals(IntegrityCrypto.sha256Hex(f.readBytes()), IntegrityCrypto.sha256Hex(f))
        } finally {
            f.delete()
            dir.delete()
        }
    }

    @Test
    fun `empty pin skips check`() {
        assertFalse(IntegrityCrypto.pinEnabled(""))
        assertFalse(IntegrityCrypto.pinEnabled("   "))
        assertFalse(IntegrityCrypto.pinEnabled(null))
        assertTrue(IntegrityCrypto.hashesMatch("anything", ""))
        assertTrue(IntegrityCrypto.hashesMatch(null, ""))
    }

    @Test
    fun `hashesMatch is case insensitive`() {
        val h = "AABBCC"
        assertTrue(IntegrityCrypto.hashesMatch("aabbcc", h))
        assertTrue(IntegrityCrypto.hashesMatch("AABBCC", "aabbcc"))
        assertFalse(IntegrityCrypto.hashesMatch("deadbeef", h))
        assertFalse(IntegrityCrypto.hashesMatch(null, h))
    }

    @Test
    fun `libHashForAbi maps abis`() {
        assertEquals("aaa", IntegrityCrypto.libHashForAbi("arm64-v8a", "AAA", "b", "c", "d"))
        assertEquals("bbb", IntegrityCrypto.libHashForAbi("armeabi-v7a", "a", "BBB", "c", "d"))
        assertEquals("ccc", IntegrityCrypto.libHashForAbi("x86_64", "a", "b", "CCC", "d"))
        assertEquals("ddd", IntegrityCrypto.libHashForAbi("x86", "a", "b", "c", "DDD"))
        assertEquals("", IntegrityCrypto.libHashForAbi("mips", "a", "b", "c", "d"))
    }

    @Test
    fun `debug build always ok even with bad pins`() {
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = true,
            certExpected = "deadbeef",
            certActual = "00000000",
            libExpected = "cafe",
            libFileExists = false,
            libActualHash = null,
        )
        assertTrue(v.ok)
        assertEquals(null, v.reason)
    }

    @Test
    fun `release ok when pins match`() {
        val cert = IntegrityCrypto.sha256Hex("cert".toByteArray())
        val lib = IntegrityCrypto.sha256Hex("lib".toByteArray())
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = cert,
            certActual = cert,
            libExpected = lib,
            libFileExists = true,
            libActualHash = lib,
        )
        assertTrue(v.ok)
    }

    @Test
    fun `release fails on cert mismatch`() {
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            certActual = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            libExpected = "",
            libFileExists = true,
            libActualHash = null,
        )
        assertFalse(v.ok)
        assertTrue(v.reason!!.contains("Подпись"))
    }

    @Test
    fun `release fails on missing libclient`() {
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "",
            certActual = null,
            libExpected = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            libFileExists = false,
            libActualHash = null,
        )
        assertFalse(v.ok)
        assertTrue(v.reason!!.contains("libclient") || v.reason!!.contains("VPN-модуль"))
    }

    @Test
    fun `release fails on libclient hash mismatch — tampered binary`() {
        val expected = IntegrityCrypto.sha256Hex("official".toByteArray())
        val tampered = IntegrityCrypto.sha256Hex("tampered".toByteArray())
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "",
            certActual = null,
            libExpected = expected,
            libFileExists = true,
            libActualHash = tampered,
        )
        assertFalse(v.ok)
        assertTrue(v.reason!!.contains("изменён") || v.reason!!.contains("повреждён"))
    }

    @Test
    fun `release ok when all pins empty`() {
        val v = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "",
            certActual = null,
            libExpected = "",
            libFileExists = false,
            libActualHash = null,
        )
        assertTrue(v.ok)
    }
}
