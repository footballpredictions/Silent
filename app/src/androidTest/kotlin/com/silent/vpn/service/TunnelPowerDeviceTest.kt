package com.silent.vpn.service

import android.content.Context
import android.content.ContextWrapper
import android.os.PowerManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Real service/PowerManager adapter, without starting or changing a user's VPN. */
@RunWith(AndroidJUnit4::class)
class TunnelPowerDeviceTest {
    private fun service(): SilentVpnService = SilentVpnService().also {
        ContextWrapper::class.java.getDeclaredMethod("attachBaseContext", Context::class.java)
            .apply { isAccessible = true }
            .invoke(it, InstrumentationRegistry.getInstrumentation().targetContext)
    }

    private fun call(service: SilentVpnService, name: String) {
        SilentVpnService::class.java.getDeclaredMethod(name).apply { isAccessible = true }.invoke(service)
    }

    private fun controller(service: SilentVpnService): TunnelWakeController =
        SilentVpnService::class.java.getDeclaredField("tunnelWake").apply { isAccessible = true }
            .get(service) as TunnelWakeController

    private fun held(service: SilentVpnService): Boolean =
        (SilentVpnService::class.java.getDeclaredField("wakeLock").apply { isAccessible = true }
            .get(service) as? PowerManager.WakeLock)?.isHeld == true

    @Test fun idleAndTransfer_useRealServiceCpuLock() {
        val service = service()
        val now = SystemClock.elapsedRealtime()
        try {
            call(service, "acquirePerformanceLocks")
            assertTrue(held(service))
            val controller = controller(service)
            controller.update(now + 2_000L, true, true, false, 1.0)
            controller.update(now + 70_000L, true, true, false, 1.0)
            assertFalse("idle service retained the platform CPU lock", held(service))
            controller.update(now + 80_000L, true, true, false, 1.01)
            assertTrue("background transfer lost CPU protection", held(service))
            controller.update(now + 82_000L, true, false, true, 1.01)
            assertFalse("network pause retained CPU protection", held(service))
        } finally {
            call(service, "releaseWakeLock")
        }
    }

    @Test fun missingServiceTick_platformReleasesLockItself() {
        val service = service()
        try {
            call(service, "acquirePerformanceLocks")
            assertTrue(held(service))
            val deadline = SystemClock.elapsedRealtime() + 35_000L
            while (held(service) && SystemClock.elapsedRealtime() < deadline) SystemClock.sleep(200L)
            assertFalse("stalled service acquired an unlimited CPU lock", held(service))
        } finally {
            call(service, "releaseWakeLock")
        }
    }
}
