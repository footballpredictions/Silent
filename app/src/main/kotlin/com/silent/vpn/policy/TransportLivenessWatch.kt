package com.silent.vpn.policy

/** A live native process can have frozen sockets/stdout and stale positive worker counts. */
internal class TransportLivenessWatch {
    enum class Action { NONE, VERIFY, RECOVER }

    private var observedStatsAtMs = 0L
    private var observedSinceMs = 0L
    private var triggered = false

    fun observe(statsAtMs: Long, stale: Boolean, nowMs: Long): Action {
        if (!stale || statsAtMs <= 0L) {
            reset()
            return Action.NONE
        }
        val sinceObservation = nowMs - observedSinceMs
        if (statsAtMs != observedStatsAtMs || sinceObservation > 35_000L || sinceObservation < 0L) {
            observedStatsAtMs = statsAtMs
            observedSinceMs = nowMs
            triggered = false
            return Action.VERIFY
        }
        // wdtt-go/stats.go publishes every 10s; allow its timer and stdout reader to resume.
        if (triggered || sinceObservation < 20_000L) return Action.NONE
        triggered = true
        return Action.RECOVER
    }

    fun reset() {
        observedStatsAtMs = 0L
        observedSinceMs = 0L
        triggered = false
    }
}
