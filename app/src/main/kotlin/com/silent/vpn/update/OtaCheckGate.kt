package com.silent.vpn.update

import com.silent.vpn.policy.OtaCheckPolicy

/** Tunnel-ready callbacks must survive a blocked public check and its cooldown. */
internal class OtaCheckGate {
    private var inFlight = false
    private var retryPending = false
    private var lastAttemptAtMs = 0L

    @Synchronized fun resetCooldown() {
        lastAttemptAtMs = 0L
    }

    @Synchronized fun tryStart(nowMs: Long, force: Boolean): Boolean {
        if (inFlight) {
            if (force) retryPending = true
            return false
        }
        if (OtaCheckPolicy.shouldSkipRecheck(lastAttemptAtMs, nowMs, force)) return false
        inFlight = true
        return true
    }

    @Synchronized fun finish(nowMs: Long): Boolean {
        inFlight = false
        lastAttemptAtMs = nowMs
        val retry = retryPending
        retryPending = false
        return retry
    }
}
