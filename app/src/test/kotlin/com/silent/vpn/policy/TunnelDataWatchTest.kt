package com.silent.vpn.policy

import com.silent.vpn.policy.TunnelDataWatch.Sample
import org.junit.Assert.*
import org.junit.Test

class TunnelDataWatchTest {
    @Test fun idleNeverRequestsNetworkProbes() {
        val watch = TunnelDataWatch()
        for (time in 1L..3_600_001L step 2_000L) assertFalse(watch.observe(Sample(10, 10), time))
    }
    @Test fun silentRadioGapWithLiveWorkersRequiresAProbe() {
        val watch = TunnelDataWatch()
        assertFalse(watch.observe(Sample(10, 10), 1))
        assertFalse(watch.observe(Sample(11, 10), 2_001))
        assertTrue(watch.observe(Sample(14, 10), 14_001))
    }
    @Test fun repliesAndProcessCounterResetCancelSuspicion() {
        val watch = TunnelDataWatch()
        watch.observe(Sample(10, 10), 1)
        watch.observe(Sample(11, 10), 2_001)
        assertFalse(watch.observe(Sample(12, 11), 14_001))
        assertFalse(watch.observe(Sample(0, 0), 40_001))
        assertFalse(watch.observe(Sample(0, 0), 100_001))
    }
    @Test fun probesAreBoundedAndNeedNewApplicationPackets() {
        val watch = TunnelDataWatch()
        watch.observe(Sample(10, 10), 1)
        watch.observe(Sample(11, 10), 2_001)
        assertTrue(watch.observe(Sample(12, 10), 14_001))
        watch.attempted(14_001)
        assertFalse(watch.observe(Sample(13, 10), 20_001))
        assertFalse(watch.observe(Sample(14, 10), 40_001))
        assertTrue(watch.observe(Sample(15, 10), 74_001))
        watch.attempted(74_001)
        assertFalse(watch.observe(Sample(15, 10), 150_001))
    }
}
