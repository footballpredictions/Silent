package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TunnelHttpPolicyTest {

    @Test
    fun `tunnel backend failure only 502 and 503`() {
        assertTrue(TunnelHttpPolicy.isTunnelBackendFailure(502))
        assertTrue(TunnelHttpPolicy.isTunnelBackendFailure(503))
        assertFalse(TunnelHttpPolicy.isTunnelBackendFailure(401))
        assertFalse(TunnelHttpPolicy.isTunnelBackendFailure(200))
    }

    @Test
    fun `upstream error message patterns`() {
        assertTrue(TunnelHttpPolicy.isTunnelUpstreamError("VPN upstream failed"))
        assertTrue(TunnelHttpPolicy.isTunnelUpstreamError("tunnel backend unavailable"))
        assertFalse(TunnelHttpPolicy.isTunnelUpstreamError("timeout"))
        assertFalse(TunnelHttpPolicy.isTunnelUpstreamError(null))
    }
}
