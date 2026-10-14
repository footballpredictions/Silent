package com.silent.vpn.service

/** QS is an on/off switch for the session; a network gap only changes its subtitle. */
internal object VpnTileSessionPolicy {
    data class State(val enabled: Boolean, val ready: Boolean, val captchaPending: Boolean)

    fun resolve(
        serviceRunning: Boolean,
        wdttRunning: Boolean,
        wdttReady: Boolean,
        olcrtcRunning: Boolean,
        olcrtcReady: Boolean,
        captchaPending: Boolean,
    ): State = State(
        enabled = serviceRunning,
        ready = serviceRunning && ((wdttRunning && wdttReady) || (olcrtcRunning && olcrtcReady)),
        captchaPending = serviceRunning && captchaPending,
    )
}
