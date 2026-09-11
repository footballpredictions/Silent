package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SiblingVpnPolicyTest {

    @Test
    fun `debug and release are siblings`() {
        assertEquals(
            SiblingVpnPolicy.DEBUG_PACKAGE,
            SiblingVpnPolicy.siblingPackage(SiblingVpnPolicy.RELEASE_PACKAGE),
        )
        assertEquals(
            SiblingVpnPolicy.RELEASE_PACKAGE,
            SiblingVpnPolicy.siblingPackage(SiblingVpnPolicy.DEBUG_PACKAGE),
        )
        assertNull(SiblingVpnPolicy.siblingPackage("com.other.vpn"))
        assertTrue(SiblingVpnPolicy.isSilentFamilyPackage(SiblingVpnPolicy.DEBUG_PACKAGE))
        assertFalse(SiblingVpnPolicy.isSilentFamilyPackage("com.nordvpn"))
    }

    @Test
    fun `teardown only when sibling installed and foreign vpn active`() {
        assertTrue(
            SiblingVpnPolicy.shouldRequestSiblingTeardown(
                ourPackage = SiblingVpnPolicy.RELEASE_PACKAGE,
                siblingInstalled = true,
                otherVpnActive = true,
            ),
        )
        assertFalse(
            SiblingVpnPolicy.shouldRequestSiblingTeardown(
                ourPackage = SiblingVpnPolicy.RELEASE_PACKAGE,
                siblingInstalled = false,
                otherVpnActive = true,
            ),
        )
        assertFalse(
            SiblingVpnPolicy.shouldRequestSiblingTeardown(
                ourPackage = SiblingVpnPolicy.RELEASE_PACKAGE,
                siblingInstalled = true,
                otherVpnActive = false,
            ),
        )
    }

    @Test
    fun `wg tunnel name differs for debug`() {
        assertEquals("silent", SiblingVpnPolicy.wgTunnelName(SiblingVpnPolicy.RELEASE_PACKAGE))
        assertEquals("silent_dbg", SiblingVpnPolicy.wgTunnelName(SiblingVpnPolicy.DEBUG_PACKAGE))
    }

    @Test
    fun `foreign vpn means cleanup required`() {
        assertTrue(SiblingVpnPolicy.needsForeignVpnCleanup(otherVpnActive = true))
        assertFalse(SiblingVpnPolicy.needsForeignVpnCleanup(otherVpnActive = false))
    }

    @Test
    fun `wait attempts cover full window`() {
        assertEquals(32, SiblingVpnPolicy.foreignVpnWaitAttempts(8_000L, 250L))
        assertEquals(1, SiblingVpnPolicy.foreignVpnWaitAttempts(100L, 250L))
    }
}
