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

    /**
     * QR poll/start must ignore bootstrap hijack of getServerUrl → 10.66.66.1.
     */
    fun qrLoginIgnoresBootstrapHijack(
        bootstrapTunnelReady: Boolean,
        overrideBase: String?,
        publicUrl: String,
        tunnelUrl: String,
    ): String {
        if (!overrideBase.isNullOrBlank()) return overrideBase.trimEnd('/')
        return publicUrl.trimEnd('/')
    }

    /**
     * Экран входа: приложение вне WG, API на 10.66.66.1 только через overlay
     * (иначе poll QR не доходит до Улья, хотя телефон уже подтвердил).
     */
    fun preLoginApiNeedsOverlay(
        appExcludedFromVpn: Boolean,
        vpnServiceRunning: Boolean,
        tunnelReady: Boolean,
    ): Boolean = appExcludedFromVpn && vpnServiceRunning && tunnelReady

    /**
     * QR на ТВ: приложение в ЧС туннеля, как телефон. Сначала публичный URL Улья,
     * туннель 10.66.66.1 — запасной. Иначе poll не видит already-approved сессию.
     */
    fun qrLoginPollBases(
        appExcludedFromVpn: Boolean,
        publicUrl: String,
        tunnelUrl: String,
    ): List<String> {
        val public = publicUrl.trimEnd('/')
        val tunnel = tunnelUrl.trimEnd('/')
        if (public.isBlank()) return listOf(tunnel).filter { it.isNotBlank() }
        if (tunnel.isBlank() || tunnel == public) return listOf(public)
        return if (appExcludedFromVpn) listOf(public, tunnel) else listOf(tunnel, public)
    }
}
