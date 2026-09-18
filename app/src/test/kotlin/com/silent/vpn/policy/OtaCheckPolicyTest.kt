package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class OtaCheckPolicyTest {

    @Test
    fun `wifi with vpn checks tunnel first like pc after public tls hang`() {
        assertEquals(
            OtaCheckPolicy.Channel.TUNNEL_THEN_PUBLIC,
            OtaCheckPolicy.channel(onMobileData = false, vpnUp = true),
        )
        assertTrue(OtaCheckPolicy.preferTunnelFirst(vpnUp = true))
    }

    @Test
    fun `wifi without vpn can only use public`() {
        assertEquals(
            OtaCheckPolicy.Channel.PUBLIC,
            OtaCheckPolicy.channel(onMobileData = false, vpnUp = false),
        )
        assertFalse(OtaCheckPolicy.preferTunnelFirst(vpnUp = false))
    }

    @Test
    fun `lte with vpn uses tunnel only no hanging public https`() {
        assertEquals(
            OtaCheckPolicy.Channel.TUNNEL,
            OtaCheckPolicy.channel(onMobileData = true, vpnUp = true),
        )
        assertFalse(OtaCheckPolicy.allowPublicFallback(onMobileData = true))
    }

    @Test
    fun `lte without vpn cannot check`() {
        assertEquals(
            OtaCheckPolicy.Channel.NONE,
            OtaCheckPolicy.channel(onMobileData = true, vpnUp = false),
        )
    }

    @Test
    fun `main screen rechecks after cooldown unlike once per vpn session`() {
        assertTrue(
            OtaCheckPolicy.shouldSkipRecheck(
                lastAttemptAtMs = 10_000L,
                nowMs = 20_000L,
                inOverlaySession = false,
                cooldownMs = 30_000L,
            ),
        )
        assertFalse(
            OtaCheckPolicy.shouldSkipRecheck(
                lastAttemptAtMs = 10_000L,
                nowMs = 50_000L,
                inOverlaySession = false,
                cooldownMs = 30_000L,
            ),
        )
    }

    @Test
    fun `overlay check is never skipped so lte sync can offer ota`() {
        assertFalse(
            OtaCheckPolicy.shouldSkipRecheck(
                lastAttemptAtMs = 10_000L,
                nowMs = 11_000L,
                inOverlaySession = true,
                cooldownMs = 30_000L,
            ),
        )
    }

    @Test
    fun `wifi tunnel ready triggers ota check lte waits for overlay`() {
        assertTrue(OtaCheckPolicy.shouldCheckOnTunnelReady(onMobileData = false, bootstrapMode = false))
        assertFalse(OtaCheckPolicy.shouldCheckOnTunnelReady(onMobileData = true, bootstrapMode = false))
        assertFalse(OtaCheckPolicy.shouldCheckOnTunnelReady(onMobileData = false, bootstrapMode = true))
    }

    @Test
    fun `total timeout covers github pages then short hive fallback`() {
        assertTrue(OtaCheckPolicy.TOTAL_TIMEOUT_MS < 20_000L)
        assertTrue(OtaCheckPolicy.TOTAL_TIMEOUT_MS >= OtaGithubDiscovery.FETCH_TIMEOUT_MS)
    }
}
