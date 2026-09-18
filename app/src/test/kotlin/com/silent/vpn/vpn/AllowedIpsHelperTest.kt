package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AllowedIpsHelperTest {

    private val baseConfig = """
        [Interface]
        PrivateKey = aaaa
        Address = 10.66.66.5/32

        [Peer]
        PublicKey = bbbb
        AllowedIPs = 0.0.0.0/0
        Endpoint = 1.2.3.4:51820
    """.trimIndent()

    @Test
    fun `bootstrap does not swallow cell ips when hive wg is dead`() {
        // Overlay на Улей :56000 — узкий AllowedIPs, иначе мёртвый handshake глотает соты.
        val patched = AllowedIpsHelper.patchAllowedIPsForBootstrapAuth(baseConfig, "89.125.188.100")
        assertTrue(patched.contains("AllowedIPs = 10.66.66.0/24, 89.125.188.100/32"))
        assertFalse(patched.contains("AllowedIPs = 0.0.0.0/0"))
        val line = patched.lines().first { it.startsWith("AllowedIPs") }
        val cidrs = line.removePrefix("AllowedIPs = ").split(", ")
        assertFalse("Сота 1 должна остаться на underlay", covers(cidrs, "87.58.213.193"))
        assertFalse("Сота 2 должна остаться на underlay", covers(cidrs, "78.17.74.27"))
    }

    @Test
    fun `cell overlay keeps full tunnel so mail apps get internet`() {
        val patched = AllowedIpsHelper.patchAllowedIPsForBootstrapAuth(baseConfig, "87.58.213.193")
        assertTrue(patched.contains("AllowedIPs = 0.0.0.0/0"))
        assertFalse(patched.contains("AllowedIPs = 10.66.66.0/24, 87.58.213.193/32"))
    }

    @Test
    fun `patchAllowedIPsToSubnet replaces allowed ips with wg subnet`() {
        val patched = AllowedIpsHelper.patchAllowedIPsToSubnet(baseConfig)
        assertTrue(patched.contains("AllowedIPs = 10.66.66.0/24"))
        assertFalse(patched.contains("AllowedIPs = 0.0.0.0/0"))
        // Остальные поля не тронуты
        assertTrue(patched.contains("Endpoint = 1.2.3.4:51820"))
    }

    @Test
    fun `generateExclusionAllowedIPs empty list covers everything`() {
        assertEquals("0.0.0.0/0", AllowedIpsHelper.generateExclusionAllowedIPs(emptyList()))
    }

    @Test
    fun `generateExclusionAllowedIPs ignores invalid entries`() {
        assertEquals(
            "0.0.0.0/0",
            AllowedIpsHelper.generateExclusionAllowedIPs(listOf("not-an-ip", "", "abc.def")),
        )
    }

    @Test
    fun `single exclusion does not cover excluded ip but covers neighbours`() {
        val cidrs = AllowedIpsHelper.generateExclusionAllowedIPs(listOf("87.240.190.78")).split(", ")
        assertFalse(covers(cidrs, "87.240.190.78"))
        assertTrue(covers(cidrs, "87.240.190.77"))
        assertTrue(covers(cidrs, "87.240.190.79"))
        assertTrue(covers(cidrs, "8.8.8.8"))
        assertTrue(covers(cidrs, "10.66.66.1"))
    }

    @Test
    fun `single exclusion covers exactly all addresses minus one`() {
        val cidrs = AllowedIpsHelper.generateExclusionAllowedIPs(listOf("1.2.3.4")).split(", ")
        val total = cidrs.sumOf { cidr ->
            val prefix = cidr.substringAfter('/').toInt()
            1L shl (32 - prefix)
        }
        assertEquals((1L shl 32) - 1L, total)
    }

    @Test
    fun `multiple exclusions all excluded`() {
        val ips = listOf("87.240.190.78", "87.240.190.79", "95.142.205.10")
        val cidrs = AllowedIpsHelper.generateExclusionAllowedIPs(ips).split(", ")
        for (ip in ips) {
            assertFalse("must not cover $ip", covers(cidrs, ip))
        }
        assertTrue(covers(cidrs, "8.8.8.8"))
        val total = cidrs.sumOf { 1L shl (32 - it.substringAfter('/').toInt()) }
        assertEquals((1L shl 32) - ips.size, total)
    }

    @Test
    fun `duplicate exclusions counted once`() {
        val cidrs = AllowedIpsHelper
            .generateExclusionAllowedIPs(listOf("1.2.3.4", "1.2.3.4"))
            .split(", ")
        val total = cidrs.sumOf { 1L shl (32 - it.substringAfter('/').toInt()) }
        assertEquals((1L shl 32) - 1L, total)
    }

    @Test
    fun `patchAllowedIPs with empty exclusions keeps config as is`() {
        assertEquals(baseConfig, AllowedIpsHelper.patchAllowedIPs(baseConfig, emptyList()))
    }

    @Test
    fun `patchAllowedIPs replaces line with exclusion set`() {
        val patched = AllowedIpsHelper.patchAllowedIPs(baseConfig, listOf("1.2.3.4"))
        assertFalse(patched.contains("AllowedIPs = 0.0.0.0/0"))
        val line = patched.lines().first { it.startsWith("AllowedIPs") }
        val cidrs = line.removePrefix("AllowedIPs = ").split(", ")
        assertFalse(covers(cidrs, "1.2.3.4"))
    }

    @Test
    fun `patchAllowedIPsEnsureApiSubnet appends wg subnet`() {
        val split = AllowedIpsHelper.patchAllowedIPs(baseConfig, listOf("1.2.3.4"))
        val patched = AllowedIpsHelper.patchAllowedIPsEnsureApiSubnet(split)
        assertTrue(patched.contains("10.66.66.0/24"))
        val line = patched.lines().first { it.startsWith("AllowedIPs") }
        assertTrue(line.contains("10.66.66.0/24"))
    }

    @Test
    fun `patchAllowedIPsEnsureApiSubnet is idempotent`() {
        val once = AllowedIpsHelper.patchAllowedIPsEnsureApiSubnet(baseConfig)
        val twice = AllowedIpsHelper.patchAllowedIPsEnsureApiSubnet(once)
        assertEquals(once, twice)
    }

    private fun covers(cidrs: List<String>, ip: String): Boolean {
        val target = ipToLong(ip)
        return cidrs.any { cidr ->
            val (net, prefix) = cidr.split('/')
            val p = prefix.toInt()
            val mask = if (p == 0) 0L else (0xFFFFFFFFL shl (32 - p)) and 0xFFFFFFFFL
            (target and mask) == (ipToLong(net) and mask)
        }
    }

    private fun ipToLong(ip: String): Long =
        ip.split('.').fold(0L) { acc, oct -> (acc shl 8) or (oct.toLong() and 0xFF) }
}
