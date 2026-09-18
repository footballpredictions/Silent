package com.silent.vpn.policy

/**
 * OTA check routing. Public hive HTTPS from RF often TCP-acks then TLS-hangs
 * (~20s on PC). Android used to wait on that path and then skip rechecks
 * for the rest of the VPN session — the banner never appeared.
 */
object OtaCheckPolicy {
    const val TOTAL_TIMEOUT_MS = 18_000L
    const val RECHECK_COOLDOWN_MS = 30_000L

    enum class Channel {
        NONE,
        PUBLIC,
        TUNNEL,
        TUNNEL_THEN_PUBLIC,
    }

    fun channel(onMobileData: Boolean, vpnUp: Boolean): Channel = when {
        onMobileData && !vpnUp -> Channel.NONE
        onMobileData -> Channel.TUNNEL
        vpnUp -> Channel.TUNNEL_THEN_PUBLIC
        else -> Channel.PUBLIC
    }

    fun preferTunnelFirst(vpnUp: Boolean): Boolean = vpnUp

    fun allowPublicFallback(onMobileData: Boolean): Boolean = !onMobileData

    fun shouldSkipRecheck(
        lastAttemptAtMs: Long,
        nowMs: Long,
        inOverlaySession: Boolean,
        cooldownMs: Long = RECHECK_COOLDOWN_MS,
    ): Boolean {
        if (inOverlaySession) return false
        if (lastAttemptAtMs <= 0L) return false
        return nowMs - lastAttemptAtMs < cooldownMs
    }

    fun shouldCheckOnTunnelReady(onMobileData: Boolean, bootstrapMode: Boolean): Boolean =
        !onMobileData && !bootstrapMode
}
