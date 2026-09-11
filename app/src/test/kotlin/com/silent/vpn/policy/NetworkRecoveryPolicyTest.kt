package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NetworkRecoveryPolicyTest {

    @Test
    fun `cell events do not count as our gap while wifi is alive`() {
        // Сота гаснет сама при живом Wi‑Fi — не наша дыра, рестарта быть не должно.
        assertFalse(
            NetworkRecoveryPolicy.isOurUnderlyingNetwork(
                eventFp = "cell",
                currentFp = "wifi",
                lastFp = "wifi",
            ),
        )
        // Событие нашей сети — учитываем.
        assertTrue(
            NetworkRecoveryPolicy.isOurUnderlyingNetwork(
                eventFp = "wifi",
                currentFp = "wifi",
                lastFp = "wifi",
            ),
        )
        // Полная дыра: текущего транспорта нет — ориентируемся на последний известный.
        assertTrue(
            NetworkRecoveryPolicy.isOurUnderlyingNetwork(
                eventFp = "cell",
                currentFp = "",
                lastFp = "cell",
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.isOurUnderlyingNetwork(
                eventFp = "",
                currentFp = "wifi",
                lastFp = "wifi",
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.isOurUnderlyingNetwork(
                eventFp = "unknown",
                currentFp = "",
                lastFp = "",
            ),
        )
    }

    @Test
    fun `wifi dying after default already flipped to cell is still our blackout`() {
        // Wi‑Fi onLosing, Android уже переключил default на cell — дыру wifi всё равно надо учесть
        // (иначе не будет gap/switch и после звонка/обрыва залипает до рубильника).
        assertTrue(
            NetworkRecoveryPolicy.shouldMarkUnderlyingBlackout(
                eventFp = "wifi",
                currentFp = "cell",
                lastFp = "wifi",
            ),
        )
        // Чужая сота при живом Wi‑Fi — по-прежнему нет.
        assertFalse(
            NetworkRecoveryPolicy.shouldMarkUnderlyingBlackout(
                eventFp = "cell",
                currentFp = "wifi",
                lastFp = "wifi",
            ),
        )
        // Наша текущая — да.
        assertTrue(
            NetworkRecoveryPolicy.shouldMarkUnderlyingBlackout(
                eventFp = "cell",
                currentFp = "cell",
                lastFp = "cell",
            ),
        )
    }

    @Test
    fun `after pause or blackout fast validated is not enough — need full restart`() {
        assertTrue(
            NetworkRecoveryPolicy.needsFullRestartAfterNetworkEvent(
                reason = "validated",
                wasPausedOrBlackout = true,
            ),
        )
        assertTrue(
            NetworkRecoveryPolicy.needsFullRestartAfterNetworkEvent(
                reason = "available_restored:wifi",
                wasPausedOrBlackout = true,
            ),
        )
        assertTrue(
            NetworkRecoveryPolicy.needsFullRestartAfterNetworkEvent(
                reason = "capabilities:cell",
                wasPausedOrBlackout = true,
            ),
        )
        // Без паузы короткий validated — можно fast-path.
        assertFalse(
            NetworkRecoveryPolicy.needsFullRestartAfterNetworkEvent(
                reason = "validated",
                wasPausedOrBlackout = false,
            ),
        )
        // phone_call_end / transport_switch — всегда полный.
        assertTrue(
            NetworkRecoveryPolicy.needsFullRestartAfterNetworkEvent(
                reason = "phone_call_end",
                wasPausedOrBlackout = false,
            ),
        )
    }

    @Test
    fun `call defers recovery but must replay after end`() {
        assertTrue(
            NetworkRecoveryPolicy.shouldQueueRecoveryDuringCall(
                phoneCallActive = true,
                reason = "transport_switch:mobile",
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldQueueRecoveryDuringCall(
                phoneCallActive = true,
                reason = "phone_call_end",
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldQueueRecoveryDuringCall(
                phoneCallActive = false,
                reason = "validated_after_gap",
            ),
        )
        assertEquals(
            "transport_switch:mobile",
            NetworkRecoveryPolicy.recoveryReasonAfterCallEnd("transport_switch:mobile"),
        )
        assertEquals(
            "phone_call_end",
            NetworkRecoveryPolicy.recoveryReasonAfterCallEnd(null),
        )
        assertEquals(
            "phone_call_end",
            NetworkRecoveryPolicy.recoveryReasonAfterCallEnd(""),
        )
        // Слабый available не затирает уже накопленный switch.
        assertEquals(
            "transport_switch:mobile",
            NetworkRecoveryPolicy.preferDeferredRecoveryReason(
                "transport_switch:mobile",
                "available:wifi",
            ),
        )
        assertEquals(
            "wifi_gap_restored",
            NetworkRecoveryPolicy.preferDeferredRecoveryReason(
                "available:cell",
                "wifi_gap_restored",
            ),
        )
    }

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
    fun `rat buckets 2g 3g 4g including nr as 4g`() {
        assertEquals("2g", NetworkRecoveryPolicy.ratBucketFromNetworkType(2)) // EDGE
        assertEquals("3g", NetworkRecoveryPolicy.ratBucketFromNetworkType(10)) // HSPA
        assertEquals("4g", NetworkRecoveryPolicy.ratBucketFromNetworkType(13)) // LTE
        assertEquals("4g", NetworkRecoveryPolicy.ratBucketFromNetworkType(20)) // NR
        assertEquals("", NetworkRecoveryPolicy.ratBucketFromNetworkType(0))
    }

    @Test
    fun `rat change all orders`() {
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("2g", "3g"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("3g", "4g"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("4g", "2g"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("4g", "3g"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("3g", "2g"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnRatChange("2g", "4g"))
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnRatChange("4g", "4g"))
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnRatChange("", "4g"))
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnRatChange("4g", ""))
    }

    @Test
    fun `cell gap after tower blackout`() {
        assertTrue(
            NetworkRecoveryPolicy.shouldRecoverAfterTransportGap(
                lastBlackoutAtMs = 1_000L,
                nowMs = 3_000L,
                validated = true,
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldRecoverAfterTransportGap(
                lastBlackoutAtMs = 1_000L,
                nowMs = 1_200L,
                validated = true,
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldRecoverAfterTransportGap(
                lastBlackoutAtMs = 1_000L,
                nowMs = 3_000L,
                validated = false,
            ),
        )
        assertFalse(
            NetworkRecoveryPolicy.shouldRecoverAfterTransportGap(
                lastBlackoutAtMs = 0L,
                nowMs = 10_000L,
                validated = true,
            ),
        )
    }

    @Test
    fun `validated gap ignores doze blip`() {
        assertFalse(
            NetworkRecoveryPolicy.shouldRecoverAfterValidatedGap(
                unvalidatedSinceMs = 1_000L,
                nowMs = 2_500L,
            ),
        )
        assertTrue(
            NetworkRecoveryPolicy.shouldRecoverAfterValidatedGap(
                unvalidatedSinceMs = 1_000L,
                nowMs = 1_000L + NetworkRecoveryPolicy.VALIDATED_GAP_RECOVER_MS,
            ),
        )
    }

    @Test
    fun `phone call audio modes and end`() {
        assertTrue(NetworkRecoveryPolicy.isPhoneCallAudioMode(2)) // IN_CALL
        assertTrue(NetworkRecoveryPolicy.isPhoneCallAudioMode(3)) // IN_COMMUNICATION
        assertFalse(NetworkRecoveryPolicy.isPhoneCallAudioMode(0)) // NORMAL
        assertTrue(NetworkRecoveryPolicy.shouldFirePhoneCallEnd(true, false))
        assertFalse(NetworkRecoveryPolicy.shouldFirePhoneCallEnd(false, false))
        assertFalse(NetworkRecoveryPolicy.shouldFirePhoneCallEnd(true, true))
    }

    @Test
    fun `wait restart reasons include rat gap call handover`() {
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("rat_switch:3g->4g"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("cell_gap_restored"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("wifi_gap_restored"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("link_handover:cell"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("phone_call_end"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("internet_restored"))
        assertTrue(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("transport_switch:wifi"))
        assertFalse(NetworkRecoveryPolicy.needsUnderlyingWaitRestart("validated"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("rat_switch:2g->4g"))
        assertTrue(NetworkRecoveryPolicy.isRealNetworkRecoveryReason("link_handover:wifi"))
    }

    @Test
    fun `link handover first observation is ignored`() {
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnLinkAddrsChange(null, "10.1.2.3"))
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnLinkAddrsChange("", "10.1.2.3"))
        assertTrue(NetworkRecoveryPolicy.shouldRecoverOnLinkAddrsChange("10.1.2.3", "10.9.8.7"))
        assertFalse(NetworkRecoveryPolicy.shouldRecoverOnLinkAddrsChange("10.1.2.3", "10.1.2.3"))
        assertTrue(NetworkRecoveryPolicy.shouldAcceptLinkHandover(0L, 10_000L))
        assertFalse(NetworkRecoveryPolicy.shouldAcceptLinkHandover(1_000L, 10_000L))
        assertTrue(NetworkRecoveryPolicy.shouldAcceptLinkHandover(1_000L, 32_000L))
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
