package com.silent.vpn.policy

import com.silent.vpn.ui.screens.VpnState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ConfigSyncSkipPolicyTest {

    private fun tick(
        allowsBackgroundSync: Boolean = true,
        vpnBusy: Boolean = false,
        initialOverlaySyncActive: Boolean = false,
        vpnServiceRunning: Boolean = true,
        tunnelDataSyncCompleted: Boolean = true,
        onMobileData: Boolean = false,
        vpnState: VpnState = VpnState.CONNECTED,
        nowMs: Long = 200_000L,
        tunnelDataSyncFinishedAtMs: Long = 100_000L,
    ) = ConfigSyncSkipPolicy.TickInput(
        allowsBackgroundSync = allowsBackgroundSync,
        vpnBusy = vpnBusy,
        initialOverlaySyncActive = initialOverlaySyncActive,
        vpnServiceRunning = vpnServiceRunning,
        tunnelDataSyncCompleted = tunnelDataSyncCompleted,
        onMobileData = onMobileData,
        vpnState = vpnState,
        nowMs = nowMs,
        tunnelDataSyncFinishedAtMs = tunnelDataSyncFinishedAtMs,
    )

    @Test
    fun `skip mobile without vpn`() {
        assertEquals(
            ConfigSyncSkipPolicy.SkipReason.MOBILE_WITHOUT_VPN,
            ConfigSyncSkipPolicy.skipReason(tick(allowsBackgroundSync = false)),
        )
    }

    @Test
    fun `skip vpn busy`() {
        assertEquals(
            ConfigSyncSkipPolicy.SkipReason.VPN_BUSY,
            ConfigSyncSkipPolicy.skipReason(tick(vpnBusy = true)),
        )
    }

    @Test
    fun `skip initial overlay sync`() {
        assertEquals(
            ConfigSyncSkipPolicy.SkipReason.INITIAL_OVERLAY_SYNC,
            ConfigSyncSkipPolicy.skipReason(tick(initialOverlaySyncActive = true)),
        )
    }

    @Test
    fun `skip tunnel sync pending on lte`() {
        assertEquals(
            ConfigSyncSkipPolicy.SkipReason.TUNNEL_SYNC_PENDING,
            ConfigSyncSkipPolicy.skipReason(
                tick(
                    tunnelDataSyncCompleted = false,
                    onMobileData = true,
                    vpnState = VpnState.CONNECTED,
                ),
            ),
        )
    }

    @Test
    fun `skip quiet period after tunnel sync on lte`() {
        assertEquals(
            ConfigSyncSkipPolicy.SkipReason.QUIET_AFTER_TUNNEL_SYNC,
            ConfigSyncSkipPolicy.skipReason(
                tick(
                    onMobileData = true,
                    nowMs = 150_000L,
                    tunnelDataSyncFinishedAtMs = 100_000L,
                ),
            ),
        )
        assertNull(
            ConfigSyncSkipPolicy.skipReason(
                tick(
                    onMobileData = true,
                    nowMs = 200_000L,
                    tunnelDataSyncFinishedAtMs = 100_000L,
                ),
            ),
        )
    }

    @Test
    fun `mobile sync never uses overlay on connect`() {
        assertFalse(
            ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
                ConfigSyncSkipPolicy.MobileSyncModeInput(
                    onMobileData = true,
                    appExcludedFromVpn = true,
                    vpnUpForSync = true,
                    tunnelDataSyncCompleted = false,
                ),
            ),
        )
        assertFalse(
            ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
                ConfigSyncSkipPolicy.MobileSyncModeInput(
                    onMobileData = true,
                    appExcludedFromVpn = true,
                    vpnUpForSync = true,
                    tunnelDataSyncCompleted = true,
                ),
            ),
        )
    }

    @Test
    fun `wifi subscription poll only on wifi`() {
        assertTrue(ConfigSyncSkipPolicy.wifiSubscriptionPollAllowed(onMobileData = false))
        assertFalse(ConfigSyncSkipPolicy.wifiSubscriptionPollAllowed(onMobileData = true))
    }
}
