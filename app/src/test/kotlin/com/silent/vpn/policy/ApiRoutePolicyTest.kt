package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiRoutePolicyTest {

    private fun ctx(
        onMobileData: Boolean = false,
        mainVpnTunnelUp: Boolean = false,
        tunnelDataSyncCompleted: Boolean = false,
        apiOverlayActive: Boolean = false,
        bootstrapMode: Boolean = false,
        tunnelReady: Boolean = false,
        publicReachable: Boolean? = true,
    ) = ApiRoutePolicy.RouteContext(
        onMobileData = onMobileData,
        appExcludedFromVpn = true,
        mainVpnTunnelUp = mainVpnTunnelUp,
        tunnelDataSyncCompleted = tunnelDataSyncCompleted,
        apiOverlayActive = apiOverlayActive,
        bootstrapMode = bootstrapMode,
        tunnelReady = tunnelReady,
        publicReachable = publicReachable,
    )

    @Test
    fun `mobile direct tunnel only after initial sync without overlay`() {
        assertFalse(ApiRoutePolicy.canUseMobileDirectTunnelApi(ctx(onMobileData = true, mainVpnTunnelUp = true)))
        assertTrue(
            ApiRoutePolicy.canUseMobileDirectTunnelApi(
                ctx(onMobileData = true, mainVpnTunnelUp = true, tunnelDataSyncCompleted = true),
            ),
        )
        assertFalse(
            ApiRoutePolicy.canUseMobileDirectTunnelApi(
                ctx(
                    onMobileData = true,
                    mainVpnTunnelUp = true,
                    tunnelDataSyncCompleted = true,
                    apiOverlayActive = true,
                ),
            ),
        )
    }

    @Test
    fun `routine api on lte defers until overlay before sync`() {
        assertEquals(
            ApiRoutePolicy.RoutineApiRoute.DEFER_UNTIL_OVERLAY,
            ApiRoutePolicy.routineApiRouteOnMobile(ctx(onMobileData = true, mainVpnTunnelUp = true)),
        )
    }

    @Test
    fun `routine api on lte uses tunnel block after overlay path`() {
        assertEquals(
            ApiRoutePolicy.RoutineApiRoute.TUNNEL_BLOCK,
            ApiRoutePolicy.routineApiRouteOnMobile(
                ctx(onMobileData = true, mainVpnTunnelUp = true, apiOverlayActive = true),
            ),
        )
    }

    @Test
    fun `routine api bootstrap uses tunnel when ready`() {
        assertEquals(
            ApiRoutePolicy.RoutineApiRoute.BOOTSTRAP_TUNNEL,
            ApiRoutePolicy.routineApiRouteOnMobile(
                ctx(onMobileData = true, bootstrapMode = true, tunnelReady = true),
            ),
        )
    }

    @Test
    fun `user api promo path uses overlay on lte excluded`() {
        assertEquals(
            ApiRoutePolicy.UserApiRoute.OVERLAY_BRIEF,
            ApiRoutePolicy.userApiRoute(ctx(onMobileData = true, mainVpnTunnelUp = true)),
        )
        assertEquals(
            ApiRoutePolicy.UserApiRoute.ROUTINE,
            ApiRoutePolicy.userApiRoute(ctx(onMobileData = true, mainVpnTunnelUp = true, apiOverlayActive = true)),
        )
    }

    @Test
    fun `user api on lte with app in tunnel uses routine`() {
        assertEquals(
            ApiRoutePolicy.UserApiRoute.ROUTINE,
            ApiRoutePolicy.userApiRoute(
                ctx(onMobileData = true, mainVpnTunnelUp = true).copy(appExcludedFromVpn = false),
            ),
        )
    }

    @Test
    fun `lte overlay fallback after direct failure`() {
        assertTrue(
            ApiRoutePolicy.lteRoutineNeedsOverlayFallback(
                ctx(onMobileData = true, mainVpnTunnelUp = true),
                allowOverlayFallback = true,
                directFailed = true,
            ),
        )
        assertFalse(
            ApiRoutePolicy.lteRoutineNeedsOverlayFallback(
                ctx(onMobileData = false, mainVpnTunnelUp = true),
                allowOverlayFallback = true,
                directFailed = true,
            ),
        )
    }

    @Test
    fun `wifi routine prefers public when reachable`() {
        assertTrue(ApiRoutePolicy.wifiRoutinePrefersPublic(ctx(publicReachable = true)))
        assertFalse(ApiRoutePolicy.wifiRoutinePrefersPublic(ctx(publicReachable = false)))
    }

    @Test
    fun `tv qr login uses public hive even while bootstrap tunnel is ready`() {
        assertEquals(
            "https://hive.example",
            ApiRoutePolicy.qrLoginIgnoresBootstrapHijack(
                bootstrapTunnelReady = true,
                overrideBase = null,
                publicUrl = "https://hive.example/",
                tunnelUrl = "http://10.66.66.1:8000",
            ),
        )
    }

    @Test
    fun `tv qr poll prefers public hive when app is excluded from vpn`() {
        assertEquals(
            listOf("https://hive.example", "http://10.66.66.1:8000"),
            ApiRoutePolicy.qrLoginPollBases(
                appExcludedFromVpn = true,
                publicUrl = "https://hive.example/",
                tunnelUrl = "http://10.66.66.1:8000",
            ),
        )
        assertEquals(
            listOf("http://10.66.66.1:8000", "https://hive.example"),
            ApiRoutePolicy.qrLoginPollBases(
                appExcludedFromVpn = false,
                publicUrl = "https://hive.example",
                tunnelUrl = "http://10.66.66.1:8000",
            ),
        )
    }

    @Test
    fun `tv login poll uses overlay while app is excluded from bootstrap vpn`() {
        assertTrue(
            ApiRoutePolicy.preLoginApiNeedsOverlay(
                appExcludedFromVpn = true,
                vpnServiceRunning = true,
                tunnelReady = true,
            ),
        )
        assertTrue(
            !ApiRoutePolicy.preLoginApiNeedsOverlay(
                appExcludedFromVpn = false,
                vpnServiceRunning = true,
                tunnelReady = true,
            ),
        )
        assertTrue(
            !ApiRoutePolicy.preLoginApiNeedsOverlay(
                appExcludedFromVpn = true,
                vpnServiceRunning = true,
                tunnelReady = false,
            ),
        )
    }
}
