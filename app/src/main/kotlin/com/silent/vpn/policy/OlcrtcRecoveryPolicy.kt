package com.silent.vpn.policy

/**
 * Чистые решения olcrtc recover / LTE / Wi‑Fi↔cell.
 * Логика вынесена из SilentVpnService / OlcrtcTunnelManager для юнит-тестов.
 */
object OlcrtcRecoveryPolicy {

    /** MainViewModel ждёт SOCKS ~90с — recover не должен убивать первый connect. */
    const val CONNECT_GRACE_MS = 95_000L

    /** После transport_switch не дублируем restart на тот же target. */
    const val TRANSPORT_SWITCH_DEDUP_MS = 25_000L

    /** Общий debounce recover (не switch / не restore / не retry). */
    const val RECOVER_DEBOUNCE_MS = 12_000L

    /** Watchdog: процесс жив, tunnelReady=false слишком долго. */
    const val WATCHDOG_STUCK_MS = 25_000L

    /** Watchdog: процесс мёртв после ready-сессии. */
    const val WATCHDOG_DOWN_MS = 20_000L

    /** Watchdog: SOCKS probe при ready. */
    const val WATCHDOG_SOCKS_MS = 40_000L

    /** Сколько подряд SOCKS fail нужно, прежде чем SOCKS_DEAD (speedtest грузит peer). */
    const val WATCHDOG_SOCKS_FAIL_STREAK = 3

    /**
     * Если за это окно были «tunnel to …» — peer жив, SOCKS probe к gstatic
     * может таймаутиться из‑за нагрузки (Яндекс.Интернетометр / Speedtest).
     */
    const val RECENT_TUNNEL_TRAFFIC_MS = 35_000L

    /**
     * remote not ready / sid timeout: даже при редких «tunnel to» (half-dead peer)
     * — зелёный вис. Не сбрасывать streak на traffic; после N → suspect / kill.
     */
    const val STREAM_DEAD_SUSPECT_STREAK = 3
    const val STREAM_DEAD_KILL_STREAK = 6

    /** Heartbeat/API через SOCKS fail при tunnelReady — data plane мёртв. */
    const val SOCKS_API_FAIL_SUSPECT_STREAK = 3

    /** Telemost/WB closed — даём peer шанс самовосстановиться без лишнего restart. */
    const val PEER_CLOSED_GRACE_MS = 18_000L

    /** Prefetch connection-details TTL (OkHttp cache). */
    const val PREFETCH_TTL_MS = 4 * 60_000L

    enum class RecoverDecision {
        ALLOW,
        SKIP_NO_CONFIG,
        SKIP_NOT_RUNNING,
        SKIP_NEVER_READY,
        SKIP_IN_FLIGHT,
        SKIP_SWITCH_DUP,
        SKIP_DEBOUNCE,
        SKIP_NON_CRITICAL_NETWORK,
    }

    enum class WatchdogAction {
        NONE,
        STUCK,
        DOWN,
        SOCKS_DEAD,
    }

    data class RecoverInput(
        val configJson: String?,
        val isRunning: Boolean,
        val everReady: Boolean,
        val recoverInFlight: Boolean,
        val reason: String,
        val preferFromReason: String?,
        val lastTransportSwitchTarget: String,
        val lastTransportSwitchMs: Long,
        val lastTransportRestartMs: Long,
        val nowMs: Long,
    )

    data class InitialConnectInput(
        val sessionActive: Boolean,
        val everReady: Boolean,
        val isRunning: Boolean,
        val connectStartedAtMs: Long,
        val nowMs: Long,
        val graceMs: Long = CONNECT_GRACE_MS,
    )

    data class WatchdogInput(
        val sessionActive: Boolean,
        val running: Boolean,
        val tunnelReady: Boolean,
        val recoverInFlight: Boolean,
        val initialConnectInProgress: Boolean,
        val starting: Boolean,
        val withinLibclientConnectGrace: Boolean,
        val sinceRestartMs: Long,
        val socksHealthy: Boolean,
        /** Подряд неудачных SOCKS probe (speedtest/Intermeter не должны ронять с 1 fail). */
        val socksFailStreak: Int = 0,
        /** Были ли SOCKS tunnel-сессии недавно (трафик идёт). */
        val recentTunnelTraffic: Boolean = false,
    )

    data class PeerClosedGraceInput(
        val running: Boolean,
        val iceConnected: Boolean,
        val socksHealthy: Boolean,
        val recentTunnelTraffic: Boolean = false,
        /**
         * missed_pong / stream_dead: не доверяем «recent traffic» и fake SOCKS —
         * только реальный dial (socksHealthy от force-probe).
         */
        val forceLivenessCheck: Boolean = false,
    )

    data class PrefetchReuseInput(
        val cachedRoom: String?,
        val requestRoom: String,
        val untilMs: Long,
        val nowMs: Long,
        val fileExists: Boolean,
    )

    data class UnderlyingReadySample(
        val elapsedMs: Long,
        val fingerprint: String,
        val validated: Boolean,
        val anyInternet: Boolean,
        val preferTransport: String?,
        val preferHoldMs: Long = 3_500L,
    )

    fun preferTransportFromReason(reason: String): String? = when {
        reason.startsWith("transport_switch:wifi") -> "wifi"
        reason.startsWith("transport_switch:mobile") -> "cell"
        else -> null
    }

    fun isInitialConnectInProgress(input: InitialConnectInput): Boolean =
        input.sessionActive &&
            !input.everReady &&
            input.isRunning &&
            input.nowMs - input.connectStartedAtMs < input.graceMs

    /**
     * Recover (stop→await→start) только после первого успешного tunnelReady в сессии.
     * Иначе LTE/network callbacks убивают первый connect.
     */
    fun decideRecover(input: RecoverInput): RecoverDecision {
        if (input.configJson.isNullOrBlank()) return RecoverDecision.SKIP_NO_CONFIG
        if (!input.isRunning) return RecoverDecision.SKIP_NOT_RUNNING
        if (!input.everReady) return RecoverDecision.SKIP_NEVER_READY
        if (input.recoverInFlight) return RecoverDecision.SKIP_IN_FLIGHT

        val prefer = input.preferFromReason
        if (prefer != null) {
            if (
                prefer == input.lastTransportSwitchTarget &&
                input.nowMs - input.lastTransportSwitchMs < TRANSPORT_SWITCH_DEDUP_MS
            ) {
                return RecoverDecision.SKIP_SWITCH_DUP
            }
            return RecoverDecision.ALLOW
        }

        if (!isCriticalRecoverReason(input.reason)) {
            return RecoverDecision.SKIP_NON_CRITICAL_NETWORK
        }

        if (
            input.nowMs - input.lastTransportRestartMs < RECOVER_DEBOUNCE_MS &&
            !input.reason.startsWith("phone_call_end") &&
            !input.reason.startsWith("internet_restored") &&
            !input.reason.contains(":retry")
        ) {
            return RecoverDecision.SKIP_DEBOUNCE
        }
        return RecoverDecision.ALLOW
    }

    /**
     * Для olcrtc обычные validated/available/capabilities события не должны ронять
     * живой туннель: они часто мигают на Android без реальной потери peer/SOCKS.
     */
    fun isCriticalRecoverReason(reason: String): Boolean =
        reason.startsWith("transport_switch:") ||
            reason.startsWith("internet_restored") ||
            reason.startsWith("phone_call_end") ||
            reason.startsWith("olcrtc_peer_dead:process_exit") ||
            reason.startsWith("watchdog_olcrtc_down") ||
            reason.startsWith("watchdog_olcrtc_stuck")

    /**
     * Native olcrtc сам делает reconnect на liveness (~4 мин ping).
     * Kotlin hardReset/смена комнаты = минута «зависло». Рестарт только если процесс умер.
     */
    fun shouldRestartOnPeerGlitch(reason: String): Boolean {
        val r = reason.lowercase()
        return r.contains("process_exit")
    }

    /**
     * gstatic SOCKS-проба на узком Telemost/vp8 = секунды зависания YouTube/Telegram.
     * Glitch всё равно не рестартит процесс — зонд только вредит полосе.
     * Старт: ждём ICE/peer latched, не dial к Google.
     */
    fun shouldProbeSocksWhileTunnelReady(): Boolean = false

    fun shouldForceSocksDialOnLivenessSuspect(): Boolean = false

    /** После failed recover — один retry, только если сессия уже была ready. */
    fun shouldScheduleRecoverRetry(everReady: Boolean, reason: String): Boolean =
        everReady && !reason.contains(":retry")

    /**
     * После peer_dead / watchdog: новая room только на retry / 404.
     * Первый stream_dead — комната на srv обычно жива (liveness reconnect ~4мин);
     * 60с assign при живом sticky = «подвисло минуту».
     */
    fun shouldRefreshConfigOnRecover(onMobileData: Boolean, reason: String): Boolean {
        if (reason.contains(":retry")) return true
        if (
            reason.contains("404") ||
                reason.contains("conference") ||
                reason.contains("not found", ignoreCase = true)
        ) {
            return true
        }
        // process_exit / stream_dead — та же комната; native reconnect, не новый assign.
        return false
    }

    /** Если assign не дал другую room — стартовать кеш, не сидеть минуту в CONNECTING. */
    fun shouldFallbackToCachedRoomOnReassignMiss(reason: String): Boolean =
        !reason.contains(":retry")

    /** Сколько ждать reportOlcrtcRoomFailure + assign новой room. */
    const val RECOVER_REASSIGN_TIMEOUT_MS = 20_000L

    fun decideWatchdog(input: WatchdogInput): WatchdogAction {
        if (!input.sessionActive) return WatchdogAction.NONE
        if (input.recoverInFlight || input.initialConnectInProgress || input.starting) {
            return WatchdogAction.NONE
        }
        if (input.withinLibclientConnectGrace) return WatchdogAction.NONE

        return when {
            input.running &&
                !input.tunnelReady &&
                input.sinceRestartMs > WATCHDOG_STUCK_MS -> WatchdogAction.STUCK

            !input.running &&
                !input.tunnelReady &&
                input.sinceRestartMs > WATCHDOG_DOWN_MS -> WatchdogAction.DOWN

            else -> WatchdogAction.NONE
        }
    }

    /** Speedtest/Intermeter: живой «tunnel to» = peer не мёртв. */
    fun hasRecentTunnelTraffic(lastTunnelActivityMs: Long, nowMs: Long): Boolean =
        lastTunnelActivityMs > 0L && nowMs - lastTunnelActivityMs < RECENT_TUNNEL_TRAFFIC_MS

    /**
     * После grace PC closed: restart только если peer/SOCKS не ожили
     * и нет свежего туннельного трафика (иначе speedtest ложно «убивает» сессию).
     */
    fun shouldNotifyPeerDeadAfterGrace(input: PeerClosedGraceInput): Boolean {
        if (!input.running) return false
        if (input.iceConnected) return false
        if (input.forceLivenessCheck) {
            return !input.socksHealthy
        }
        if (input.socksHealthy) return false
        if (input.recentTunnelTraffic) return false
        return true
    }

    /**
     * CONN_FILE / OkHttp prefetch: НЕ стирать на stop/before_start.
     * Иначе каждый тумблер снова ждёт Yandex auth (главный cold-start).
     * Wipe только при смене room или явном clear.
     */
    fun shouldInvalidatePrefetchOnStop(): Boolean = false

    /**
     * In-memory или диск: тот же room + живой TTL + файл.
     * cachedRoom может прийти с диска (после kill app), не только из RAM.
     */
    fun shouldReusePrefetchCache(input: PrefetchReuseInput): Boolean {
        val room = input.cachedRoom?.trim().orEmpty()
        if (room.isEmpty()) return false
        val want = input.requestRoom.trim()
        if (want.isEmpty()) return false
        if (room != want && !want.contains(room) && !room.contains(want)) return false
        if (!input.fileExists) return false
        if (input.untilMs <= input.nowMs) return false
        return true
    }

    /** Нормализация prefer для awaitUnderlyingReady. */
    fun normalizePreferTransport(preferTransport: String?): String? = when (preferTransport) {
        "wifi", "eth" -> "wifi"
        "mobile", "cell" -> "cell"
        else -> null
    }

    /**
     * Решение «сеть готова» без Android API — для тестов LTE/airplane/preferHold.
     * Зеркалит VpnNetworkHelper.awaitUnderlyingReady.
     */
    fun shouldAcceptUnderlyingReady(sample: UnderlyingReadySample): Boolean {
        val want = normalizePreferTransport(sample.preferTransport)
        if (sample.validated) {
            val match = when (want) {
                "wifi" -> sample.fingerprint == "wifi" || sample.fingerprint == "eth"
                "cell" -> sample.fingerprint == "cell"
                else -> sample.fingerprint.isNotEmpty()
            }
            if (match || want == null || sample.elapsedMs >= sample.preferHoldMs) {
                return true
            }
        }
        // LTE после airplane часто без VALIDATED — any INTERNET после 1.2с + preferHold.
        if (
            sample.anyInternet &&
            sample.elapsedMs >= 1_200L &&
            (want == null || sample.elapsedMs >= sample.preferHoldMs)
        ) {
            return true
        }
        return false
    }

    fun shouldAcceptUnderlyingReadyOnTimeout(anyInternet: Boolean): Boolean = anyInternet

    /**
     * Network recovery во время первого connect — пропускаем целиком
     * (включая transport_switch / validated / watchdog).
     */
    fun shouldSkipNetworkRecoveryDuringInitialConnect(
        initialConnectInProgress: Boolean,
        reason: String,
    ): Boolean {
        if (!initialConnectInProgress) return false
        // Disconnect / revoke не через этот путь — reason всегда network/peer.
        return true
    }

    fun isOlcrtcSessionLive(
        sessionActive: Boolean,
        running: Boolean,
        tunnelReady: Boolean,
        lastConfigPresent: Boolean,
    ): Boolean = sessionActive || running || tunnelReady || lastConfigPresent
}
