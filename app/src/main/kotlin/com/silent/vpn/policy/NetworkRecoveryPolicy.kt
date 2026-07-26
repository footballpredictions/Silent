package com.silent.vpn.policy

import com.silent.vpn.policy.VpnNetworkConstants.MIN_TRANSPORT_RESTART_INTERVAL_MS

object NetworkRecoveryPolicy {

    fun wifiCellTransportTarget(oldFp: String, newFp: String): String? = when {
        oldFp == "cell" && newFp == "wifi" -> "wifi"
        oldFp == "wifi" && newFp == "cell" -> "mobile"
        else -> null
    }

    fun isRealNetworkRecoveryReason(reason: String): Boolean {
        val base = reason.substringBefore(':')
        return base == "available" ||
            base == "capabilities" ||
            base == "capabilities_restored" ||
            base == "available_restored" ||
            base == "lost_restored" ||
            base == "restored" ||
            base == "transport_switch" ||
            base == "validated" ||
            base == "internet_restored" ||
            base == "phone_call_end" ||
            base == "olcrtc_peer_dead" ||
            base == "watchdog_olcrtc_down"
    }

    fun isSpuriousRecoveryReason(reason: String): Boolean {
        val base = reason.substringBefore(':')
        return base == "unhealthy" || base == "stale" || base == "watchdog_down"
    }

    data class TransportRestartInput(
        val bootstrapMode: Boolean,
        val reason: String,
        val transportHealthy: Boolean,
        val workerRampUpActive: Boolean,
        val activeWorkers: Int,
        val totalWorkers: Int?,
        val lastTransportRestartMs: Long,
        val nowMs: Long,
        val minRestartIntervalMs: Long = MIN_TRANSPORT_RESTART_INTERVAL_MS,
    )

    fun shouldSkipTransportRestart(input: TransportRestartInput): Boolean {
        if (input.bootstrapMode) return true
        if (isRealNetworkRecoveryReason(input.reason)) return false
        if (!input.transportHealthy) return false
        if (input.workerRampUpActive) return true
        if (input.activeWorkers < 1) return false
        val total = input.totalWorkers ?: return isSpuriousRecoveryReason(input.reason)
        if (input.activeWorkers < total / 2) return false
        val sinceRestart = input.nowMs - input.lastTransportRestartMs
        if (isSpuriousRecoveryReason(input.reason)) {
            if (input.lastTransportRestartMs > 0L && sinceRestart < input.minRestartIntervalMs) return true
            return true
        }
        if (input.reason.startsWith("restart:") &&
            input.lastTransportRestartMs > 0L &&
            sinceRestart < input.minRestartIntervalMs
        ) {
            return true
        }
        return false
    }

    fun shouldDeferRecoveryForPhoneCall(phoneCallActive: Boolean): Boolean = phoneCallActive
}
