package com.silent.vpn.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.silent.vpn.policy.ApiRoutePolicy
import com.silent.vpn.test.NetworkAssumptions
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import dagger.hilt.android.testing.HiltAndroidRule

/**
 * Маршрутизация OTA / ConfigSync / promo на **реальной** сети устройства.
 * Wi‑Fi-ветки и LTE-ветки разделены через [NetworkAssumptions] (skip, не fail).
 */
@HiltAndroidTest
@RunWith(AndroidJUnit4::class)
class RepositoryRoutingInstrumentedTest {

    @get:org.junit.Rule
    val hiltRule = HiltAndroidRule(this)

    @Inject
    lateinit var repo: SilentRepository

    @Before
    fun setUp() {
        hiltRule.inject()
    }

    @Test
    fun wifi_otaUsesGitHubNotTunnel() {
        NetworkAssumptions.assumeWifi()
        val url = repo.resolveUpdateDownloadUrl(
            UpdateCheckResponse(
                available = true,
                version = "9.9.9",
                github_download_url = "https://github.com/silentvpn3/test/app.apk",
                tunnel_download_url = "/api/updates/download/android",
            ),
        )
        assertTrue(url!!.contains("github.com"))
        assertFalse(repo.shouldUseTunnelUpdateDownload())
    }

    @Test
    fun wifi_allowsBackgroundConfigSyncWithoutVpn() {
        NetworkAssumptions.assumeWifi()
        assertTrue(repo.allowsBackgroundConfigSync())
    }

    @Test
    fun wifi_promoUsesRoutineApiRoute() {
        NetworkAssumptions.assumeWifi()
        val route = ApiRoutePolicy.userApiRoute(
            ApiRoutePolicy.RouteContext(
                onMobileData = repo.isOnMobileData(),
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                mainVpnTunnelUp = repo.isMainVpnTunnelUp(),
                tunnelDataSyncCompleted = true,
                apiOverlayActive = false,
                bootstrapMode = false,
                tunnelReady = false,
            ),
        )
        assertEquals(ApiRoutePolicy.UserApiRoute.ROUTINE, route)
    }

    @Test
    fun lte_withoutVpn_blocksBackgroundConfigSync() {
        NetworkAssumptions.assumeMobileData()
        if (repo.isMainVpnTunnelUp()) {
            org.junit.Assume.assumeTrue("VPN уже включён — отключите для этой проверки", false)
        }
        assertFalse(repo.allowsBackgroundConfigSync())
    }

    @Test
    fun lte_withVpn_otaUsesTunnelDownload() {
        NetworkAssumptions.assumeMobileData()
        NetworkAssumptions.assumeSilentVpnUp()
        assertTrue(repo.shouldUseTunnelUpdateDownload())
        val url = repo.resolveUpdateDownloadUrl(
            UpdateCheckResponse(
                available = true,
                tunnel_download_url = "/api/updates/download/android",
                github_download_url = "https://github.com/silentvpn3/ignored.apk",
            ),
        )
        assertTrue(url!!.contains("10.66.66.1"))
    }

    @Test
    fun lte_withVpn_promoNeedsOverlayBrief() {
        NetworkAssumptions.assumeMobileData()
        NetworkAssumptions.assumeSilentVpnUp()
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
}
