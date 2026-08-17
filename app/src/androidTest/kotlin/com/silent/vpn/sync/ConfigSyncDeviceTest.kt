package com.silent.vpn.sync

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.policy.ConfigSyncSkipPolicy
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.test.NetworkAssumptions
import com.silent.vpn.ui.screens.VpnState
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import javax.inject.Inject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** ConfigSync skip/overlay на реальной сети + состоянии VPN-сервиса. */
@HiltAndroidTest
@RunWith(AndroidJUnit4::class)
class ConfigSyncDeviceTest {

    @get:org.junit.Rule
    val hiltRule = HiltAndroidRule(this)

    @Inject
    lateinit var repo: SilentRepository

    @Before
    fun setUp() {
        hiltRule.inject()
    }

    @Test
    fun wifi_tickNotSkippedWhenVpnIdle() {
        NetworkAssumptions.assumeWifi()
        org.junit.Assume.assumeFalse("VPN busy", VpnSessionState.isBusy())
        val skip = ConfigSyncSkipPolicy.skipReason(
            ConfigSyncSkipPolicy.TickInput(
                allowsBackgroundSync = repo.allowsBackgroundConfigSync(),
                vpnBusy = VpnSessionState.isBusy(),
                initialOverlaySyncActive = VpnSessionState.initialOverlaySyncActive,
                vpnServiceRunning = SilentVpnService.isRunning,
                tunnelDataSyncCompleted = VpnSessionState.tunnelDataSyncCompleted,
                onMobileData = repo.isOnMobileData(),
                vpnState = VpnState.CONNECTED,
                nowMs = System.currentTimeMillis(),
                tunnelDataSyncFinishedAtMs = VpnSessionState.tunnelDataSyncFinishedAtMs,
            ),
        )
        assertNull(skip)
    }

    @Test
    fun lte_withoutVpn_skipsMobileWithoutVpnTunnel() {
        NetworkAssumptions.assumeMobileData()
        if (repo.isMainVpnTunnelUp()) {
            org.junit.Assume.assumeTrue("Отключите VPN для проверки skip на LTE", false)
        }
        val skip = ConfigSyncSkipPolicy.skipReason(
            ConfigSyncSkipPolicy.TickInput(
                allowsBackgroundSync = repo.allowsBackgroundConfigSync(),
                vpnBusy = false,
                initialOverlaySyncActive = false,
                vpnServiceRunning = SilentVpnService.isRunning,
                tunnelDataSyncCompleted = VpnSessionState.tunnelDataSyncCompleted,
                onMobileData = true,
                vpnState = VpnState.DISCONNECTED,
                nowMs = System.currentTimeMillis(),
                tunnelDataSyncFinishedAtMs = 0L,
            ),
        )
        assertEquals(ConfigSyncSkipPolicy.SkipReason.MOBILE_WITHOUT_VPN, skip)
    }

    @Test
    fun lte_withVpn_doesNotUseOverlay() {
        NetworkAssumptions.assumeMobileData()
        NetworkAssumptions.assumeSilentVpnUp()
        val overlay = ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
            ConfigSyncSkipPolicy.MobileSyncModeInput(
                onMobileData = true,
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                vpnUpForSync = repo.isMainVpnTunnelUp(),
                tunnelDataSyncCompleted = false,
            ),
        )
        assertTrue(!overlay)
        assertTrue(
            ConfigSyncSkipPolicy.lteUsesInBandConfigSync(
                onMobileData = true,
                appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
            ),
        )
    }
}
