package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PaymentTunnelPolicyTest {
    @Test
    fun `payment background API requests keep full browser tunnel while login retains old overlay`() {
        assertFalse(PaymentTunnelPolicy.needsApiOverlay(true, true))
        assertFalse(PaymentTunnelPolicy.needsApiOverlay(false, true))
        assertFalse(PaymentTunnelPolicy.needsApiOverlay(false, false))
        assertTrue(PaymentTunnelPolicy.needsApiOverlay(true, false))
    }

    @Test
    fun `interface without transport must not open browser`() {
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, true, false, 0, false, true))
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, false, true, 0, false, true))
    }

    @Test
    fun `turn bypass ready without waiting for worker stats`() {
        assertTrue(PaymentTunnelPolicy.canPrepareBrowser(true, true, true, 0, false, true))
        assertTrue(PaymentTunnelPolicy.canPrepareBrowser(true, true, true, 1, false, true))
    }

    @Test
    fun `wait until overlay ends and turn bypass is known`() {
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, true, true, 1, true, true))
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, true, true, 1, false, false))
        assertTrue(PaymentTunnelPolicy.canPrepareBrowser(true, true, true, 1, false, true))
    }

    @Test
    fun `stopped or main tunnel cannot be repurposed by payment preparation`() {
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(false, true, true, 1, false, true))
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, false, true, 1, false, true))
        assertFalse(PaymentTunnelPolicy.canPrepareBrowser(true, true, false, 1, false, true))
    }

    @Test
    fun `only actual ipv4 addresses enable full route preparation`() {
        assertTrue(PaymentTunnelPolicy.isIpv4Host("87.240.190.78"))
        for (s in listOf("turn.example", "turn:87.240.190.78", "", "1.2.3.256", "1.2.3.-1", "::1")) {
            assertFalse(s, PaymentTunnelPolicy.isIpv4Host(s))
        }
    }
}
