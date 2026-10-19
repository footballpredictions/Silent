package com.silent.vpn.vpn

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LanBypassRoutesTest {
    @Test
    fun defaultHomeRangesCoverTypicalRoutersButNotWgApi() {
        val cidrs = LanBypassRoutes.defaultHomeLanCidrs()
        assertTrue(cidrs.contains("192.168.0.0/16"))
        assertTrue(cidrs.contains("172.16.0.0/12"))
        assertFalse(cidrs.any { it.startsWith("10.") })
    }

    @Test
    fun sanitizeDropsWgTunnelAndNonPrivate() {
        val out = LanBypassRoutes.sanitizeLanCidrs(
            listOf(
                "192.168.1.0/24",
                "10.66.66.0/24",
                "10.66.0.5/32",
                "8.8.8.8/32",
                "10.0.0.0/8",
                "172.16.5.0/24",
            ),
        )
        assertEquals(listOf("172.16.5.0/24", "192.168.1.0/24"), out)
    }

    @Test
    fun mergeKeepsSiteHolesAndAddsLan() {
        val out = LanBypassRoutes.mergeExcludeCidrs(
            siteHoles = listOf("1.2.3.4/32", "5.6.7.0/24"),
            lanCidrs = LanBypassRoutes.defaultHomeLanCidrs(),
        )
        assertTrue(out.contains("1.2.3.4/32"))
        assertTrue(out.contains("5.6.7.0/24"))
        assertTrue(out.contains("192.168.0.0/16"))
        assertFalse(out.contains("10.66.66.0/24"))
    }

    @Test
    fun hostAddressPrefixesCannotExcludeTheTunnelApiOrPublicNetworks() {
        assertEquals(
            listOf("10.65.1.2/16", "10.67.1.2/16"),
            LanBypassRoutes.sanitizeLanCidrs(listOf(
                "10.1.2.3/8", "10.64.1.2/14", "10.65.1.2/16", "10.67.1.2/16",
                "192.168.1.1/1", "172.16.1.1/4",
            )),
        )
    }
}
