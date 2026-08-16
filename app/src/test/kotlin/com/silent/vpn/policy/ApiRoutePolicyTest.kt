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
    fun `routine api on lte uses public when app excluded`() {
        assertEquals(
            ApiRoutePolicy.RoutineApiRoute.PUBLIC,
            ApiRoutePolicy.routineApiRouteOnMobile(ctx(onMobileData = true, mainVpnTunnelUp = true)),
        )
    }

    @Test
    fun `routine api on lte uses public even if overlay flag set`() {
        assertEquals(
            ApiRoutePolicy.RoutineApiRoute.PUBLIC,
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
    fun `user api promo path uses routine on lte excluded`() {
        assertEquals(
            ApiRoutePolicy.UserApiRoute.ROUTINE,
            ApiRoutePolicy.userApiRoute(ctx(onMobileData = true, mainVpnTunnelUp = true)),
        )
        assertEquals(
            ApiRoutePolicy.UserApiRoute.ROUTINE,
            ApiRoutePolicy.userApiRoute(ctx(onMobileData = true, mainVpnTunnelUp = true, apiOverlayActive = true)),
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
}
