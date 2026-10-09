package com.silent.vpn.service

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnNotificationGateTest {
    @Test fun `eight hours of idle VPN publish one notification instead of waking system repeatedly`() {
        val gate = VpnNotificationGate()
        val updates = (0L..8 * 60 * 60 * 1000L step 2_000L).count {
            gate.shouldPublish(true, "Активных: 60 | Трафик: 1.00 МБ", it)
        }
        assertEquals(1, updates)
    }

    @Test fun `ready transitions publish immediately without waiting for stats throttle`() {
        val gate = VpnNotificationGate()
        assertTrue(gate.shouldPublish(false, "Подключение", 0L))
        assertTrue(gate.shouldPublish(true, "Активен", 500L))
        assertTrue(gate.shouldPublish(false, "Подключение", 1_000L))
    }

    @Test fun `changed traffic retries after throttle and a new session republishes same state`() {
        val gate = VpnNotificationGate()
        assertTrue(gate.shouldPublish(true, "1.00 МБ", 0L))
        assertFalse(gate.shouldPublish(true, "1.10 МБ", 2_000L))
        assertTrue(gate.shouldPublish(true, "1.10 МБ", 4_000L))
        gate.reset()
        assertTrue(gate.shouldPublish(true, "1.10 МБ", 4_001L))
    }
}
