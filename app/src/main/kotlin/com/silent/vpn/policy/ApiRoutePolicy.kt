package com.silent.vpn.policy

/** Маршрутизация backend API (LTE overlay / Wi‑Fi public / tunnel direct). */
object ApiRoutePolicy {

    data class RouteContext(
        val onMobileData: Boolean,
        val appExcludedFromVpn: Boolean,
        val mainVpnTunnelUp: Boolean,
        val tunnelDataSyncCompleted: Boolean,
        val apiOverlayActive: Boolean,
        val bootstrapMode: Boolean,
        val tunnelReady: Boolean,
        val publicReachable: Boolean? = null,
    )

    enum class RoutineApiRoute {
        PUBLIC,
        BOOTSTRAP_TUNNEL,
        TUNNEL_BLOCK,
        DEFER_UNTIL_OVERLAY,
    }

    enum class UserApiRoute {
        ROUTINE,
        OVERLAY_BRIEF,
    }

    fun canUseMobileDirectTunnelApi(ctx: RouteContext): Boolean =
        ctx.onMobileData &&
            ctx.appExcludedFromVpn &&
            ctx.mainVpnTunnelUp &&
            ctx.tunnelDataSyncCompleted &&
            !ctx.apiOverlayActive

    /** Routine API на LTE+VPN до initial sync — только через overlay-сессию. */
    fun routineApiRouteOnMobile(ctx: RouteContext): RoutineApiRoute {
        if (ctx.bootstrapMode && ctx.tunnelReady) return RoutineApiRoute.BOOTSTRAP_TUNNEL
        if (ctx.mainVpnTunnelUp) {
            if (ctx.appExcludedFromVpn && !ctx.apiOverlayActive) {
                return RoutineApiRoute.DEFER_UNTIL_OVERLAY
            }
            return RoutineApiRoute.TUNNEL_BLOCK
        }
        return RoutineApiRoute.PUBLIC
    }

    /** Promo / оплата / user action на LTE+VPN excluded. */
    fun userApiRoute(ctx: RouteContext): UserApiRoute {
        if (ctx.appExcludedFromVpn && ctx.onMobileData && ctx.mainVpnTunnelUp && !ctx.apiOverlayActive) {
            return UserApiRoute.OVERLAY_BRIEF
        }
        return UserApiRoute.ROUTINE
    }

    /** Wi‑Fi: public если доступен, иначе tunnel. */
    fun wifiRoutinePrefersPublic(ctx: RouteContext): Boolean =
        !ctx.onMobileData && (ctx.publicReachable != false)

    fun lteRoutineNeedsOverlayFallback(
        ctx: RouteContext,
        allowOverlayFallback: Boolean,
        directFailed: Boolean,
    ): Boolean =
        ctx.onMobileData &&
            allowOverlayFallback &&
            directFailed &&
            ctx.appExcludedFromVpn &&
            ctx.mainVpnTunnelUp
}
