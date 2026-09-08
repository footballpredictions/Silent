package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Ipv6LeakPolicyTest {

    @Test
    fun `go backend builder must not get an ipv6 address — that breaks wg set address`() {
        assertFalse(Ipv6LeakPolicy.shouldCaptureIpv6OnGoBackendBuilder())
    }

    @Test
    fun `wireguard allowed ips stay ipv4`() {
        assertTrue(Ipv6LeakPolicy.isWireGuardAllowedIpsSafe("0.0.0.0/0"))
        assertTrue(Ipv6LeakPolicy.isWireGuardAllowedIpsSafe("0.0.0.0/1, 128.0.0.0/1"))
        assertFalse(Ipv6LeakPolicy.isWireGuardAllowedIpsSafe("0.0.0.0/0, ::/0"))
        assertFalse(Ipv6LeakPolicy.isWireGuardAllowedIpsSafe("::/0"))
    }
}
