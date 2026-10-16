package com.silent.vpn.policy

/** Counts plaintext packets on the VPN path; idle time and keepalives are not failures. */
internal class TunnelDataWatch {
    data class Sample(val sent: Long, val received: Long)
    private var previous: Sample? = null
    private var waitingSince = 0L
    private var attemptedSent = -1L
    private var lastAttempt = 0L

    fun observe(sample: Sample, now: Long): Boolean {
        val old = previous
        previous = sample
        if (old == null || sample.sent < old.sent || sample.received < old.received) {
            waitingSince = 0L
            attemptedSent = -1L
            return false
        }
        if (sample.received > old.received) {
            waitingSince = 0L
            return false
        }
        if (sample.sent > old.sent && waitingSince == 0L) waitingSince = now
        return waitingSince > 0L && now - waitingSince >= 12_000L &&
            sample.sent > attemptedSent && (lastAttempt == 0L || now - lastAttempt >= 60_000L)
    }

    fun attempted(now: Long) {
        attemptedSent = previous?.sent ?: -1L
        lastAttempt = now
        waitingSince = 0L
    }

    fun reset() {
        previous = null
        waitingSince = 0L
        attemptedSent = -1L
        lastAttempt = 0L
    }
}
