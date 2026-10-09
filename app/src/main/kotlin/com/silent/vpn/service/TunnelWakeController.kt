package com.silent.vpn.service

/** Owns the CPU lock independently of Android, so idle sessions can be replayed. */
internal class TunnelWakeController(private val lock: Lock) {
    interface Lock {
        val isHeld: Boolean
        fun acquire(timeoutMs: Long)
        fun release()
    }

    private var connectionUntilMs = 0L
    private var trafficUntilMs = 0L
    private var acquiredUntilMs = 0L
    private var lastTrafficMb: Double? = null
    private var wasReady = false

    @Synchronized
    fun onConnect(nowMs: Long) {
        connectionUntilMs = nowMs + 120_000L
        trafficUntilMs = 0L
        lastTrafficMb = null
        wasReady = false
        refreshLock(nowMs)
    }

    @Synchronized
    fun onRecovery(nowMs: Long) {
        connectionUntilMs = maxOf(connectionUntilMs, nowMs + 60_000L)
        refreshLock(nowMs)
    }

    @Synchronized
    fun update(
        nowMs: Long,
        sessionRunning: Boolean,
        tunnelReady: Boolean,
        paused: Boolean,
        trafficMb: Double,
        continuousTraffic: Boolean = false,
    ) {
        if (!sessionRunning) {
            stop()
            return
        }
        if (paused) {
            stop()
            lastTrafficMb = trafficMb.takeIf { it.isFinite() && it >= 0.0 }
            return
        }
        if (tunnelReady && !wasReady) {
            connectionUntilMs = 0L
            trafficUntilMs = nowMs + 45_000L
        } else if (!tunnelReady && wasReady) {
            connectionUntilMs = maxOf(connectionUntilMs, nowMs + 60_000L)
        }
        val total = trafficMb.takeIf { it.isFinite() && it >= 0.0 }
        if (total != null) {
            val previous = lastTrafficMb
            if (previous != null && total > previous) trafficUntilMs = nowMs + 45_000L
            // A restarted native process resets the counter; it is not traffic.
            lastTrafficMb = total
        }
        // Legacy debug RTC has no byte counter; retain its transfer protection.
        if (continuousTraffic && tunnelReady) trafficUntilMs = nowMs + 45_000L
        wasReady = tunnelReady
        refreshLock(nowMs)
    }

    private fun refreshLock(nowMs: Long) {
        val remaining = maxOf(connectionUntilMs, trafficUntilMs) - nowMs
        if (remaining <= 0L) {
            if (lock.isHeld) lock.release()
            acquiredUntilMs = 0L
            return
        }
        // Every platform acquire expires, even if the service's job stalls.
        if (!lock.isHeld || acquiredUntilMs - nowMs <= 10_000L) {
            val timeout = minOf(remaining, 30_000L)
            lock.acquire(timeout)
            acquiredUntilMs = nowMs + timeout
        }
    }

    @Synchronized
    fun stop() {
        if (lock.isHeld) lock.release()
        connectionUntilMs = 0L
        trafficUntilMs = 0L
        acquiredUntilMs = 0L
        lastTrafficMb = null
        wasReady = false
    }
}
