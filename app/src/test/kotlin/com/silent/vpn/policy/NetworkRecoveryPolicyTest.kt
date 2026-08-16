package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetworkRecoveryPolicyTest {

    @Test
    fun `wifi cell transport target`() {
        assertEquals("wifi", NetworkRecoveryPolicy.wifiCellTransportTarget("cell", "wifi"))
        assertEquals("mobile", NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "cell"))
        assertEquals(null, NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "wifi"))
    }

    @Test
    fun `real recovery reasons`() {
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("transport_switch"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("validated:extra"))
        assertFalse(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("unhealthy"))
    }

    @Test
    fun `spurious recovery reasons`() {
        assertTrue(NetworkRecoveryPolicy.isSpuriousRecoveryReason("stale"))
        assertTrue(NetworkRecoveryPolicy.isSpuriousRecoveryReason("watchdog_down:1"))
        assertFalse(NetworkRecoveryPolicy.isSpuriousRecoveryReason("available"))
    }

    @Test
    fun `skip transport restart in bootstrap`() {
        assertTrue(
            NetworkRecoveryPolicy.shouldSkipTransportRestart(
                NetworkRecoveryPolicy.TransportRestartInput(
                    bootstrapMode = true,
                    reason = "available",
                    transportHealthy = true,
                    workerRampUpActive = false,
                    activeWorkers = 36,
                    totalWorkers = 36,
                    lastTransportRestartMs = 0L,
                    nowMs = 100_000L,
                ),
            ),
        )
    }

    @Test
    fun `never skip real recovery reason`() {
        assertFalse(
            NetworkRecoveryPolicy.shouldSkipTransportRestart(
                NetworkRecoveryPolicy.TransportRestartInput(
                    bootstrapMode = false,
                    reason = "transport_switch",
                    transportHealthy = true,
                    workerRampUpActive = true,
                    activeWorkers = 36,
                    totalWorkers = 36,
                    lastTransportRestartMs = 0L,
                    nowMs = 100_000L,
                ),
            ),
        )
    }

    @Test
    fun `skip spurious reason when workers healthy`() {
        assertTrue(
            NetworkRecoveryPolicy.shouldSkipTransportRestart(
                NetworkRecoveryPolicy.TransportRestartInput(
                    bootstrapMode = false,
                    reason = "stale",
                    transportHealthy = true,
                    workerRampUpActive = false,
                    activeWorkers = 30,
                    totalWorkers = 36,
                    lastTransportRestartMs = 10_000L,
                    nowMs = 50_000L,
                ),
            ),
        )
    }

    @Test
    fun `olcrtc recovery reasons are real not spurious`() {
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("olcrtc_peer_dead:x"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("watchdog_olcrtc_down"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("watchdog_olcrtc_stuck"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("watchdog_olcrtc_socks"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("transport_switch:mobile"))
        assertFalse(NetworkRecoveryPolicy.isSpuriousRecoveryReason("watchdog_olcrtc_down"))
    }

    @Test
    fun `doze validated drop is still online if radio has internet`() {
        assertTrue(NetworkRecoveryPolicy.nextUnderlyingOnlineFlag(false, true))
        assertFalse(NetworkRecoveryPolicy.nextUnderlyingOnlineFlag(false, false))
        assertTrue(NetworkRecoveryPolicy.nextUnderlyingOnlineFlag(true, false))
    }

    @Test
    fun `do not pause on brief radio hole`() {
        assertFalse(
            NetworkRecoveryPolicy.shouldPauseForLostInternet(
                anyOnline = false,
                alreadyPaused = false,
                noInternetSinceMs = 1_000L,
                nowMs = 5_000L,
            ),
        )
        assertTrue(
            NetworkRecoveryPolicy.shouldPauseForLostInternet(
                anyOnline = false,
                alreadyPaused = false,
                noInternetSinceMs = 1_000L,
                nowMs = 1_000L + NetworkRecoveryPolicy.PAUSE_AFTER_NO_INTERNET_MS,
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldPauseForLostInternet(
                anyOnline = true,
                alreadyPaused = false,
                noInternetSinceMs = 1L,
                nowMs = 30_000L,
            ),
        )
    }

    @Test
    fun `restore after pause without validated`() {
        assertTrue(
            NetworkRecoveryPolicy.shouldRestoreAfterInternet(
                wasOnline = false,
                pausedForNetwork = true,
                anyOnline = true,
                validatedOnline = false,
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldRestoreAfterInternet(
                wasOnline = true,
                pausedForNetwork = false,
                anyOnline = true,
                validatedOnline = false,
            ),
        )
    }
}
