package com.silent.vpn.service

/** Suppresses duplicate foreground notifications without losing state changes. */
internal class VpnNotificationGate(private val minIntervalMs: Long = 3_000L) {
    private var lastReady: Boolean? = null
    private var lastBody: String? = null
    private var lastAtMs = 0L

    @Synchronized
    fun shouldPublish(ready: Boolean, body: String, nowMs: Long): Boolean {
        if (lastReady == ready) {
            if (lastBody == body) return false
            if (nowMs - lastAtMs < minIntervalMs) return false
        }
        lastReady = ready
        lastBody = body
        lastAtMs = nowMs
        return true
    }

    @Synchronized
    fun reset() {
        lastReady = null
        lastBody = null
        lastAtMs = 0L
    }
}
