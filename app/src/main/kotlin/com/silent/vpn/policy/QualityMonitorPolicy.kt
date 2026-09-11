package com.silent.vpn.policy

/**
 * Пассивная оценка качества туннеля (admin debug).
 * Не спидтест: смотрим дельту WG-байт и доступность tunnel API.
 */
object QualityMonitorPolicy {

    /** Ниже — «медленно», если за окно реально шёл трафик. */
    const val SLOW_DOWN_MBPS = 5.0
    const val SLOW_UP_MBPS = 0.5

    /** Меньше байт за окно = idle, не жалоба на скорость. ~64 КБ / 60 с. */
    const val MIN_ACTIVE_BYTES = 64L * 1024

    /** Handshake старше этого — канал сомнителен. */
    const val STALE_HANDSHAKE_SEC = 180

    /** Tunnel /health дольше — деградация пути до Улья. */
    const val SLOW_TUNNEL_RTT_MS = 2500.0

    enum class Verdict {
        IDLE,
        OK,
        SLOW,
        HANDSHAKE_STALE,
        TUNNEL_API_FAIL,
    }

    data class SampleInput(
        val elapsedMs: Long,
        val rxDelta: Long,
        val txDelta: Long,
        val handshakeAgeSec: Long? = null,
        val tunnelRttMs: Double? = null,
        val tunnelApiOk: Boolean = true,
    )

    data class SampleResult(
        val verdict: Verdict,
        val downMbps: Double,
        val upMbps: Double,
        val likelyCause: String,
    )

    fun mbps(bytes: Long, elapsedMs: Long): Double {
        if (elapsedMs <= 0L || bytes <= 0L) return 0.0
        return (bytes.toDouble() * 8.0) / (elapsedMs.toDouble() / 1000.0) / 1_000_000.0
    }

    fun evaluate(input: SampleInput): SampleResult {
        val down = mbps(input.rxDelta, input.elapsedMs)
        val up = mbps(input.txDelta, input.elapsedMs)
        if (!input.tunnelApiOk) {
            return SampleResult(
                Verdict.TUNNEL_API_FAIL,
                down,
                up,
                "tunnel_api_unreachable_via_vpn",
            )
        }
        val hs = input.handshakeAgeSec
        if (hs != null && hs > STALE_HANDSHAKE_SEC) {
            return SampleResult(
                Verdict.HANDSHAKE_STALE,
                down,
                up,
                "wireguard_handshake_stale",
            )
        }
        val rtt = input.tunnelRttMs
        if (rtt != null && rtt >= SLOW_TUNNEL_RTT_MS) {
            return SampleResult(
                Verdict.SLOW,
                down,
                up,
                "high_tunnel_rtt_path_or_wrap",
            )
        }
        val active = (input.rxDelta + input.txDelta) >= MIN_ACTIVE_BYTES
        if (!active) {
            return SampleResult(Verdict.IDLE, down, up, "idle_no_traffic")
        }
        if (down < SLOW_DOWN_MBPS || up < SLOW_UP_MBPS) {
            return SampleResult(
                Verdict.SLOW,
                down,
                up,
                "low_throughput_likely_mobile_or_wrap",
            )
        }
        return SampleResult(Verdict.OK, down, up, "ok")
    }

    /** Сколько подряд «плохих» сэмплов нужно, чтобы писать проблему / слать на сервер. */
    fun isProblem(verdict: Verdict): Boolean =
        verdict == Verdict.SLOW ||
            verdict == Verdict.HANDSHAKE_STALE ||
            verdict == Verdict.TUNNEL_API_FAIL

    fun shouldEscalate(consecutiveProblems: Int, needed: Int = 2): Boolean =
        consecutiveProblems >= needed
}
