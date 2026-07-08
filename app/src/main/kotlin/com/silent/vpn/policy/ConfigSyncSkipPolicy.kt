package com.silent.vpn.policy

import com.silent.vpn.policy.VpnNetworkConstants.POST_TUNNEL_SYNC_QUIET_MS
import com.silent.vpn.ui.screens.VpnState

object ConfigSyncSkipPolicy {

    enum class SkipReason {
        MOBILE_WITHOUT_VPN,
        VPN_BUSY,
        INITIAL_OVERLAY_SYNC,
        TUNNEL_SYNC_PENDING,
        QUIET_AFTER_TUNNEL_SYNC,
    }

    data class TickInput(
        val allowsBackgroundSync: Boolean,
        val vpnBusy: Boolean,
        val initialOverlaySyncActive: Boolean,
        val vpnServiceRunning: Boolean,
        val tunnelDataSyncCompleted: Boolean,
        val onMobileData: Boolean,
        val vpnState: VpnState,
        val nowMs: Long,
        val tunnelDataSyncFinishedAtMs: Long,
        val quietPeriodMs: Long = POST_TUNNEL_SYNC_QUIET_MS,
    )

    data class MobileSyncModeInput(
        val onMobileData: Boolean,
        val appExcludedFromVpn: Boolean,
        val vpnUpForSync: Boolean,
        val tunnelDataSyncCompleted: Boolean,
    )

    fun skipReason(input: TickInput): SkipReason? {
        if (!input.allowsBackgroundSync) return SkipReason.MOBILE_WITHOUT_VPN
        if (input.vpnBusy) return SkipReason.VPN_BUSY
        if (input.initialOverlaySyncActive) return SkipReason.INITIAL_OVERLAY_SYNC
        if (input.vpnServiceRunning &&
            !input.tunnelDataSyncCompleted &&
            (input.vpnState == VpnState.CONNECTING || input.onMobileData)
        ) {
            return SkipReason.TUNNEL_SYNC_PENDING
        }
        if (input.onMobileData &&
            input.tunnelDataSyncCompleted &&
            input.nowMs - input.tunnelDataSyncFinishedAtMs < input.quietPeriodMs
        ) {
            return SkipReason.QUIET_AFTER_TUNNEL_SYNC
        }
        return null
    }

    /** LTE excluded: overlay только до завершения initial tunnel sync. */
    fun mobileSyncUsesOverlay(input: MobileSyncModeInput): Boolean =
        input.onMobileData &&
            input.appExcludedFromVpn &&
            input.vpnUpForSync &&
            !input.tunnelDataSyncCompleted

    fun wifiSubscriptionPollAllowed(onMobileData: Boolean): Boolean = !onMobileData
}
