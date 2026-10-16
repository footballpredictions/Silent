package com.silent.vpn.service

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TunnelWakeControllerTest {
    private class CpuLock : TunnelWakeController.Lock {
        override var isHeld = false
        val acquisitions = mutableListOf<Long>()
        override fun acquire(timeoutMs: Long) {
            acquisitions += timeoutMs
            isHeld = true
        }
        override fun release() { isHeld = false }
    }

    @Test fun `idle connected session allows CPU sleep instead of holding it all night`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        // Actual service cadence: same traffic snapshot on every stats tick.
        for (time in 2_000L..8 * 60 * 60 * 1000L step 2_000L) {
            controller.update(time, true, true, false, 1.0)
        }
        assertFalse("idle VPN held the CPU for eight hours", lock.isHeld)
    }

    @Test fun `network pause releases CPU while callbacks remain registered`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        controller.update(2_000L, true, false, true, 0.0)
        assertFalse("offline VPN must not keep the CPU awake", lock.isHeld)
    }

    @Test fun `connection lock has a platform timeout even if coroutine stops ticking`() {
        val lock = CpuLock()
        TunnelWakeController(lock).onConnect(0L)
        assertTrue("unbounded platform acquire", lock.acquisitions.all { it in 1L..60_000L })
    }

    @Test fun `background download keeps CPU awake and releases after it finishes`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        for (time in 10_000L..300_000L step 10_000L) {
            controller.update(time, true, true, false, time / 10_000.0)
            assertTrue("download was allowed to sleep", lock.isHeld)
        }
        controller.update(370_000L, true, true, false, 30.0)
        assertFalse("finished download kept CPU awake", lock.isHeld)
    }

    @Test fun `stalled connection has a finite grace and a real recovery gets a new one`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        controller.update(200_000L, true, false, false, 0.0)
        assertFalse("stalled connect held CPU forever", lock.isHeld)
        controller.onRecovery(201_000L)
        assertTrue("network recovery needs time to establish transport", lock.isHeld)
        controller.update(400_000L, true, false, false, 0.0)
        assertFalse("stalled recovery held CPU forever", lock.isHeld)
    }

    @Test fun `native counter reset does not look like data but subsequent packets do`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        controller.update(2_000L, true, true, false, 100.0)
        controller.update(70_000L, true, true, false, 100.0)
        assertFalse(lock.isHeld)
        controller.update(80_000L, true, true, false, 0.0)
        assertFalse("counter reset woke the CPU", lock.isHeld)
        controller.update(90_000L, true, true, false, 0.01)
        assertTrue("new data did not acquire transfer protection", lock.isHeld)
    }

    @Test fun `stop releases even when traffic or legacy RTC protection was active`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        controller.update(2_000L, true, true, false, 1.0, continuousTraffic = true)
        assertTrue(lock.isHeld)
        controller.update(4_000L, false, true, false, 2.0, continuousTraffic = true)
        assertFalse(lock.isHeld)
    }

    @Test fun `legacy RTC keeps bounded protection until its byte counter is available`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        for (time in 2_000L..600_000L step 2_000L) {
            controller.update(time, true, true, false, 0.0, continuousTraffic = true)
            assertTrue(lock.isHeld)
        }
        assertTrue(lock.acquisitions.all { it in 1L..30_000L })
        controller.update(602_000L, true, false, true, 0.0, continuousTraffic = true)
        assertFalse(lock.isHeld)
    }

    @Test fun `keepalive sized counter change gives only a finite awake window`() {
        val lock = CpuLock()
        val controller = TunnelWakeController(lock)
        controller.onConnect(0L)
        controller.update(2_000L, true, true, false, 1.0)
        controller.update(120_000L, true, true, false, 1.01)
        assertTrue(lock.isHeld)
        controller.update(180_000L, true, true, false, 1.01)
        assertFalse("one background packet kept renewing the lease", lock.isHeld)
    }
}
