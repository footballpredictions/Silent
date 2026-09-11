package com.silent.vpn.policy

/**
 * Пассивная оценка качества туннеля (admin debug).
 * Не спидтест: смотрим дельту WG-байт и доступность tunnel API.
 */
object QualityMonitorPolicy {

    /** Ниже — «медленно», если за окно реально шёл трафик. */
    const val SLOW_DOWN_MBPS = 5.0
    const val SLOW_UP_MBPS = 0.5

    /** Меньше байт за окно = idle. База ~64 КБ на 60 с; короткое окно — пропорционально. */
    const val MIN_ACTIVE_BYTES = 64L * 1024
    const val MIN_ACTIVE_BYTES_FLOOR = 8L * 1024

    /** Handshake старше этого — канал сомнителен. */
    const val STALE_HANDSHAKE_SEC = 180

    /** Tunnel /health дольше — деградация пути до Улья. */
    const val SLOW_TUNNEL_RTT_MS = 2500.0

    /** Ручной Quality: длиннее окно, чтобы YouTube успел качнуть. */
    const val MANUAL_SAMPLE_WINDOW_MS = 12_000L

    fun minActiveBytesForWindow(elapsedMs: Long): Long {
        if (elapsedMs <= 0L) return MIN_ACTIVE_BYTES
        val scaled = MIN_ACTIVE_BYTES * elapsedMs / 60_000L
        return scaled.coerceAtLeast(MIN_ACTIVE_BYTES_FLOOR)
    }

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
        val hs = input.handshakeAgeSec
        val handshakeFresh = hs != null && hs in 0..STALE_HANDSHAKE_SEC
        val active = (input.rxDelta + input.txDelta) >= minActiveBytesForWindow(input.elapsedMs)

        // Tunnel API (10.66.66.1) — мягкий сигнал: excluded-app часто не достаёт GW,
        // пока YouTube/WG живы. Жёсткий fail только если канал похож на мёртвый.
        if (!input.tunnelApiOk && !handshakeFresh && !active) {
            return SampleResult(
                Verdict.TUNNEL_API_FAIL,
                down,
                up,
                "tunnel_api_unreachable_via_vpn",
            )
        }
        val apiSoft = !input.tunnelApiOk

        if (hs != null && hs > STALE_HANDSHAKE_SEC) {
            return SampleResult(
                Verdict.HANDSHAKE_STALE,
                down,
                up,
                annotate(apiSoft, "wireguard_handshake_stale"),
            )
        }
        val rtt = input.tunnelRttMs
        if (rtt != null && rtt >= SLOW_TUNNEL_RTT_MS) {
            return SampleResult(
                Verdict.SLOW,
                down,
                up,
                annotate(apiSoft, "high_tunnel_rtt_path_or_wrap"),
            )
        }
        if (!active) {
            return SampleResult(
                Verdict.IDLE,
                down,
                up,
                annotate(apiSoft, "idle_no_traffic"),
            )
        }
        if (down < SLOW_DOWN_MBPS || up < SLOW_UP_MBPS) {
            return SampleResult(
                Verdict.SLOW,
                down,
                up,
                annotate(apiSoft, "low_throughput_likely_mobile_or_wrap"),
            )
        }
        return SampleResult(
            Verdict.OK,
            down,
            up,
            annotate(apiSoft, "ok"),
        )
    }

    private fun annotate(apiSoft: Boolean, cause: String): String =
        if (apiSoft) "$cause;tunnel_api_soft_fail" else cause

    /** Сколько подряд «плохих» сэмплов нужно, чтобы писать проблему / слать на сервер. */
    fun isProblem(verdict: Verdict): Boolean =
        verdict == Verdict.SLOW ||
            verdict == Verdict.HANDSHAKE_STALE ||
            verdict == Verdict.TUNNEL_API_FAIL

    fun shouldEscalate(consecutiveProblems: Int, needed: Int = 2): Boolean =
        consecutiveProblems >= needed

    /** Папка в общей памяти: Download/SilentVPN/ (не Android/data/…). */
    const val PUBLIC_FOLDER = "SilentVPN"
    const val DOWNLOADS_DIR = "Download"

    /** quality-YYYYMMDD-HHmmss.jsonl — время создания, без MediaStore-копий с одним именем. */
    fun qualityFileName(dayYyyyMmDd: String, timeHHmmss: String): String =
        "quality-$dayYyyyMmDd-$timeHHmmss.jsonl"

    /** RELATIVE_PATH для MediaStore.Downloads — со слэшем в конце. */
    fun mediaStoreRelativePath(): String = "$DOWNLOADS_DIR/$PUBLIC_FOLDER/"

    fun publicPathHint(fileName: String): String =
        "/storage/emulated/0/$DOWNLOADS_DIR/$PUBLIC_FOLDER/$fileName"

    /** Варианты RELATIVE_PATH — OEM/Android 16 иногда без завершающего `/`. */
    fun mediaStoreRelativePathCandidates(): List<String> {
        val base = "$DOWNLOADS_DIR/$PUBLIC_FOLDER"
        return listOf("$base/", base)
    }
}
