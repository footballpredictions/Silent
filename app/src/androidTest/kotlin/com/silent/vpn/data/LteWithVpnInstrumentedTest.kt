package com.silent.vpn.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.silent.vpn.policy.ApiRoutePolicy
import com.silent.vpn.policy.ConfigSyncSkipPolicy
import com.silent.vpn.policy.UpdateUrlResolver
import com.silent.vpn.test.DeviceNetworkReporter
import com.silent.vpn.test.NetworkAssumptions
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * LTE + VPN routing на реальном [ConnectivityManager].
 *
 * **Не поднимает VPN из теста** — иначе cold-start instrumented-теста убивает уже включённый туннель
 * (`prepareForConnect` → forceStop orphan WG).
 *
 * Проверяем policy/URL так же, как в unit-тестах, но с живым LTE на устройстве.
 */
@HiltAndroidTest
@RunWith(AndroidJUnit4::class)
class LteWithVpnInstrumentedTest {

    @get:org.junit.Rule
    val hiltRule = HiltAndroidRule(this)

    @Inject
    lateinit var repo: SilentRepository

    @Before
    fun setUp() {
        hiltRule.inject()
        NetworkAssumptions.assumeMobileData()
        DeviceNetworkReporter.logState(NetworkAssumptions.targetContext())
    }

    private fun lteVpnOtaInput() = UpdateUrlResolver.OtaUrlInput(
        onMobileData = true,
        appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
        mainVpnTunnelUp = true,
        isBootstrapMode = false,
        publicServerUrl = repo.getPublicServerUrl(),
        otaPlatform = "android",
    )

    @Test
    fun lte_withVpn_otaUsesTunnelDownload() {
        assertTrue(UpdateUrlResolver.shouldUseTunnelUpdateDownload(lteVpnOtaInput()))
        val url = UpdateUrlResolver.resolveUpdateDownloadUrl(
            lteVpnOtaInput().copy(
                tunnelDownloadPath = "/api/updates/download/android",
                githubDownloadUrl = "https://github.com/silentvpn3/ignored.apk",
            ),
        )
        assertTrue(url!!.contains("10.66.66.1"))
    }

    @Test
    fun lte_withVpn_promoNeedsOverlayBrief() {
        val route = ApiRoutePolicy.userApiRoute(
            ApiRoutePolicy.RouteContext(
                onMobileData = true,
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                mainVpnTunnelUp = true,
                tunnelDataSyncCompleted = true,
                apiOverlayActive = false,
                bootstrapMode = false,
                tunnelReady = true,
            ),
        )
        assertEquals(ApiRoutePolicy.UserApiRoute.OVERLAY_BRIEF, route)
    }

    @Test
    fun lte_withVpn_configSyncUsesOverlayBeforeInitialSync() {
        val overlay = ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
            ConfigSyncSkipPolicy.MobileSyncModeInput(
                onMobileData = true,
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                vpnUpForSync = true,
                tunnelDataSyncCompleted = false,
            ),
        )
        assertTrue(overlay)
    }

    @Test
    fun lte_withVpn_configSyncDirectAfterInitialSync() {
        val overlay = ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
            ConfigSyncSkipPolicy.MobileSyncModeInput(
                onMobileData = true,
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                vpnUpForSync = true,
                tunnelDataSyncCompleted = true,
            ),
        )
        assertTrue(!overlay)
    }
}
