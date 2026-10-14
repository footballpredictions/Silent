package com.silent.vpn.policy

/** Coalesces callbacks without losing a handover to a later, weaker availability event. */
internal class NetworkRecoveryQueue {
    data class Request(val reason: String, val dueAtMs: Long)

    private var pending: Request? = null
    var wakeUntilMs = 0L
        private set
    var inFlight = false
        private set

    /** Returns true once when an online event needs a bounded CPU lease for this recovery. */
    fun enqueue(reason: String, nowMs: Long, delayMs: Long, allowWake: Boolean = false): Boolean {
        val current = pending
        if (current == null && !inFlight) wakeUntilMs = 0L
        val grantedWake = allowWake && wakeUntilMs == 0L
        if (grantedWake) wakeUntilMs = nowMs + 60_000L
        pending = Request(
            NetworkRecoveryPolicy.preferDeferredRecoveryReason(current?.reason, reason),
            minOf(current?.dueAtMs ?: Long.MAX_VALUE, nowMs + delayMs.coerceAtLeast(0L)),
        )
        return grantedWake
    }

    fun remainingDelayMs(nowMs: Long): Long? = pending?.let { (it.dueAtMs - nowMs).coerceAtLeast(0L) }

    fun begin(nowMs: Long): Request? {
        if (inFlight) return null
        val request = pending ?: return null
        if (request.dueAtMs > nowMs) return null
        pending = null
        inFlight = true
        return request
    }

    fun finish() {
        inFlight = false
    }

    /** A confirmed new radio outage ends the previous online attempt's CPU budget. */
    fun noteOffline() {
        wakeUntilMs = 0L
    }

    fun clear() {
        pending = null
        inFlight = false
        wakeUntilMs = 0L
    }
}
