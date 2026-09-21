package com.silent.vpn.policy

/** Payment depends on connectivity, not cached subscription/profile state or plan tier. */
internal object PaymentTunnelPolicy {
    fun needsBridge(
        mainTunnelUp: Boolean,
        mobile: Boolean,
        bootstrapAvailable: Boolean,
        publicBackendReachable: Boolean,
    ): Boolean = !mainTunnelUp && (mobile || bootstrapAvailable || !publicBackendReachable)

    /**
     * Browser routes: WG up + TURN outside tunnel.
     * Не ждём activeWorkers — stats приходят раз в ~10с и только тормозят оплату.
     */
    fun canPrepareBrowser(
        bootstrap: Boolean,
        running: Boolean,
        tunnelReady: Boolean,
        activeWorkers: Int,
        overlayActive: Boolean,
        hasTurnExclusions: Boolean,
    ): Boolean = bootstrap && running && tunnelReady &&
        !overlayActive && hasTurnExclusions

    fun isIpv4Host(value: String): Boolean {
        val parts = value.split('.')
        return parts.size == 4 && parts.all { part ->
            part.isNotEmpty() && part.all { it in '0'..'9' } &&
                part.toIntOrNull()?.let { it in 0..255 } == true
        }
    }
}
