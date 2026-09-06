package com.silent.vpn.policy

import com.silent.vpn.policy.VpnNetworkConstants.MIN_TRANSPORT_RESTART_INTERVAL_MS

object NetworkRecoveryPolicy {

    /** Карман/doze: radio на секунды теряет INTERNET — не убиваем libclient сразу. */
    const val PAUSE_AFTER_NO_INTERNET_MS = 8_000L

    /** VALIDATED мигает в doze <2с; дыра между вышками обычно длиннее. */
    const val VALIDATED_GAP_RECOVER_MS = 3_500L

    /** Окно, в котором возврат того же wifi/cell после blackout = реальное восстановление. */
    const val TRANSPORT_GAP_MAX_MS = 60_000L

    /**
     * Событие пришло по сети, на которой мы реально живём?
     *
     * Колбэк слушает все не-VPN сети, поэтому при живом Wi‑Fi прилетают события
     * соты, которую Android поднимает и гасит сам (IMS, MMS, чужие приложения).
     * Считать их дырой нашей сети нельзя — иначе получаем «восстановление»
     * и полный рестарт транспорта на неподвижном телефоне.
     */
    fun isOurUnderlyingNetwork(eventFp: String, currentFp: String, lastFp: String): Boolean {
        if (eventFp.isEmpty()) return false
        val ours = currentFp.ifEmpty { lastFp }
        return ours.isNotEmpty() && eventFp == ours
    }

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
            base == "validated_after_gap" ||
            base == "internet_restored" ||
            base == "phone_call_end" ||
            base == "olcrtc_peer_dead" ||
            base == "watchdog_olcrtc_down" ||
            base == "watchdog_olcrtc_stuck" ||
            base == "watchdog_olcrtc_socks" ||
            base == "underlying_blackout" ||
            base == "rat_switch" ||
            base == "cell_gap_restored" ||
            base == "wifi_gap_restored" ||
            base == "link_handover"
    }

    /**
     * Полный restart libclient + ожидание underlying.
     * Fast-path (только reapply WG) эти причины ломают: сокеты уже мертвы.
     */
    fun needsUnderlyingWaitRestart(reason: String): Boolean {
        val base = reason.substringBefore(':')
        return base == "transport_switch" ||
            base == "rat_switch" ||
            base == "cell_gap_restored" ||
            base == "wifi_gap_restored" ||
            base == "link_handover" ||
            base == "validated_after_gap" ||
            base == "internet_restored" ||
            base == "phone_call_end"
    }

    /**
     * TelephonyManager.NETWORK_TYPE_* без android-зависимости (JVM-тесты).
     * 4G и 5G (NR/LTE_CA) в одном ведре — NSA часто мигает LTE↔NR.
     */
    fun ratBucketFromNetworkType(type: Int): String = when (type) {
        1, 2, 4, 7, 11, 16 -> "2g" // GPRS/EDGE/CDMA/1xRTT/IDEN/GSM
        3, 5, 6, 8, 9, 10, 12, 14, 15, 17 -> "3g" // UMTS/EVDO/HSPA/EHRPD/TD-SCDMA
        13, 18, 19, 20 -> "4g" // LTE / IWLAN / LTE_CA / NR
        else -> ""
    }

    fun shouldRecoverOnRatChange(oldBucket: String, newBucket: String): Boolean =
        oldBucket.isNotEmpty() && newBucket.isNotEmpty() && oldBucket != newBucket

    fun shouldRecoverAfterTransportGap(
        lastBlackoutAtMs: Long,
        nowMs: Long,
        validated: Boolean,
        minGapMs: Long = 400L,
        maxGapMs: Long = TRANSPORT_GAP_MAX_MS,
    ): Boolean {
        if (!validated || lastBlackoutAtMs <= 0L) return false
        val dt = nowMs - lastBlackoutAtMs
        return dt in minGapMs..maxGapMs
    }

    fun shouldRecoverAfterValidatedGap(
        unvalidatedSinceMs: Long,
        nowMs: Long,
        minGapMs: Long = VALIDATED_GAP_RECOVER_MS,
    ): Boolean {
        if (unvalidatedSinceMs <= 0L) return false
        return nowMs - unvalidatedSinceMs >= minGapMs
    }

    fun shouldAcceptLinkHandover(
        lastHandoverMs: Long,
        nowMs: Long,
        dedupMs: Long = 30_000L,
    ): Boolean = lastHandoverMs <= 0L || nowMs - lastHandoverMs >= dedupMs

    fun shouldRecoverOnLinkAddrsChange(prev: String?, next: String): Boolean =
        !prev.isNullOrEmpty() && next.isNotEmpty() && prev != next

    /** AudioManager.MODE_RINGTONE/IN_CALL/IN_COMMUNICATION/CALL_SCREENING. */
    fun isPhoneCallAudioMode(mode: Int): Boolean = mode == 1 || mode == 2 || mode == 3 || mode == 4

    fun shouldFirePhoneCallEnd(wasActive: Boolean, callModeNow: Boolean): Boolean =
        wasActive && !callModeNow

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

    /** Пауза только после устойчивой дыры, не по миганию VALIDATED. */
    fun shouldPauseForLostInternet(
        anyOnline: Boolean,
        alreadyPaused: Boolean,
        noInternetSinceMs: Long,
        nowMs: Long,
        pauseAfterMs: Long = PAUSE_AFTER_NO_INTERNET_MS,
    ): Boolean {
        if (alreadyPaused || anyOnline) return false
        if (noInternetSinceMs <= 0L) return false
        return nowMs - noInternetSinceMs >= pauseAfterMs
    }

    fun shouldRestoreAfterInternet(
        wasOnline: Boolean?,
        pausedForNetwork: Boolean,
        anyOnline: Boolean,
        validatedOnline: Boolean,
    ): Boolean = (wasOnline == false || pausedForNetwork) && (anyOnline || validatedOnline)

    /**
     * Флаг «сеть была»: INTERNET на underlying, без требования VALIDATED.
     * Иначе doze на LTE каждые 2 с шлёт internet_restored и рвёт туннель.
     */
    fun nextUnderlyingOnlineFlag(validatedOnline: Boolean, anyOnline: Boolean): Boolean =
        validatedOnline || anyOnline
}
