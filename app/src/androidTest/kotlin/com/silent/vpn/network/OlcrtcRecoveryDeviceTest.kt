package com.silent.vpn.network

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.policy.NetworkRecoveryPolicy
import com.silent.vpn.policy.OlcrtcRecoveryPolicy
import com.silent.vpn.test.NetworkAssumptions
import com.silent.vpn.vpn.VpnNetworkHelper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Device smoke: policy olcrtc + живой fingerprint сети.
 * Полный peer/TUN на CI не поднимаем — матрица решений покрыта unit-тестами.
 */
@RunWith(AndroidJUnit4::class)
class OlcrtcRecoveryDeviceTest {

    @Test
    fun initialConnectBlocksRecoverOnLiveDevice() {
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            OlcrtcRecoveryPolicy.decideRecover(
                OlcrtcRecoveryPolicy.RecoverInput(
                    configJson = """{"bypass_family":"olcrtc"}""",
                    isRunning = true,
                    everReady = false,
                    recoverInFlight = false,
                    reason = "transport_switch:mobile",
                    preferFromReason = "cell",
                    lastTransportSwitchTarget = "",
                    lastTransportSwitchMs = 0L,
                    lastTransportRestartMs = 0L,
                    nowMs = System.currentTimeMillis(),
                ),
            ),
        )
    }

    @Test
    fun transportSwitchWifiCell_mapsToPreferAndAllowAfterReady() {
        val toMobile = NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "cell")
        val toWifi = NetworkRecoveryPolicy.wifiCellTransportTarget("cell", "wifi")
        assertEquals("mobile", toMobile)
        assertEquals("wifi", toWifi)
        assertEquals("cell", OlcrtcRecoveryPolicy.preferTransportFromReason("transport_switch:$toMobile"))
        assertEquals("wifi", OlcrtcRecoveryPolicy.preferTransportFromReason("transport_switch:$toWifi"))

        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            OlcrtcRecoveryPolicy.decideRecover(
                OlcrtcRecoveryPolicy.RecoverInput(
                    configJson = "{}",
                    isRunning = true,
                    everReady = true,
                    recoverInFlight = false,
                    reason = "transport_switch:$toMobile",
                    preferFromReason = "cell",
                    lastTransportSwitchTarget = "",
                    lastTransportSwitchMs = 0L,
                    lastTransportRestartMs = 0L,
                    nowMs = System.currentTimeMillis(),
                ),
            ),
        )
    }

    @Test
    fun prefetchSurvivesStop_diskReuseOk() {
        assertFalse(OlcrtcRecoveryPolicy.shouldInvalidatePrefetchOnStop())
        assertTrue(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = "room",
                    requestRoom = "room",
                    untilMs = System.currentTimeMillis() + 60_000L,
                    nowMs = System.currentTimeMillis(),
                    fileExists = true,
                ),
            ),
        )
    }

    @Test
    fun liveUnderlyingFingerprint_feedsAwaitPolicy() {
        NetworkAssumptions.assumeUnderlyingInternet()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val fp = VpnNetworkHelper.underlyingTransportFingerprint(context)
        val validated = VpnNetworkHelper.hasUnderlyingInternet(context)
        val any = VpnNetworkHelper.hasAnyUnderlyingInternet(context)
        assertTrue(fp.isNotEmpty())
        assertTrue(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 5_000L,
                    fingerprint = fp,
                    validated = validated,
                    anyInternet = any,
                    preferTransport = if (fp == "cell") "cell" else "wifi",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
    }

    @Test
    fun mobileRecoverSkipsConfigRefresh() {
        assertFalse(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = true,
                reason = "olcrtc_peer_dead:peer_closed",
            ),
        )
    }
}
