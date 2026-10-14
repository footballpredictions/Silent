package com.silent.vpn.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnTileSessionPolicyTest {
    private fun state(
        owner: Boolean = true,
        wdttRunning: Boolean = false,
        wdttReady: Boolean = false,
        rtcRunning: Boolean = false,
        rtcReady: Boolean = false,
        captcha: Boolean = false,
    ) = VpnTileSessionPolicy.resolve(owner, wdttRunning, wdttReady, rtcRunning, rtcReady, captcha)

    @Test
    fun `WDTT ready gap keeps on off switch enabled`() {
        assertTrue(state(wdttRunning = true, wdttReady = true).ready)
        val recovering = state(wdttRunning = true)
        assertTrue(recovering.enabled)
        assertFalse(recovering.ready)
    }

    @Test
    fun `stopped native transport during network pause keeps session enabled`() {
        val paused = state()
        assertTrue(paused.enabled)
        assertFalse(paused.ready)
    }

    @Test
    fun `RTC recovery keeps session enabled until its owner stops`() {
        assertTrue(state(rtcRunning = true, rtcReady = true).ready)
        assertTrue(state(rtcRunning = true).enabled)
        assertFalse(state(rtcRunning = true).ready)
        assertFalse(state(owner = false, rtcRunning = true, rtcReady = true).enabled)
    }

    @Test
    fun `stale transport flags cannot resurrect a stopped session`() {
        val stopped = state(owner = false, wdttRunning = true, wdttReady = true, rtcRunning = true, rtcReady = true)
        assertFalse(stopped.enabled)
        assertFalse(stopped.ready)
    }

    @Test
    fun `ready flag without running transport is connecting`() {
        assertFalse(state(wdttReady = true, rtcReady = true).ready)
    }

    @Test
    fun `captcha subtitle belongs only to enabled session`() {
        assertTrue(state(captcha = true).captchaPending)
        val staleCaptcha = state(owner = false, captcha = true)
        assertFalse(staleCaptcha.enabled)
        assertFalse(staleCaptcha.captchaPending)
    }
}
