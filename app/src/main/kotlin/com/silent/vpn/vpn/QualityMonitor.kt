package com.silent.vpn.vpn

import android.content.Context
import com.silent.vpn.BuildConfig
import com.silent.vpn.policy.QualityMonitorPolicy
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Admin + debug only: пассивный мониторинг скорости туннеля.
 * Отчёты на сервер только при проблемах; локальный файл — каждый вердикт.
 */
object QualityMonitor {
    private const val TAG = "QualityMonitor"
    private const val SAMPLE_MS = 60_000L
    private const val MANUAL_WINDOW_MS = QualityMonitorPolicy.MANUAL_SAMPLE_WINDOW_MS
    private const val MAX_QUEUE = 40

    data class Snapshot(
        val rxBytes: Long,
        val txBytes: Long,
        val handshakeAgeSec: Long?,
    )

    data class Pending(
        val atMs: Long,
        val body: JSONObject,
        var attempts: Int = 0,
    )

    data class MeasureResult(
        val ok: Boolean,
        val verdict: String,
        val summary: String,
        val path: String,
        val rowJson: String,
    )

    interface Host {
        fun isEnabled(): Boolean
        fun isVpnUp(): Boolean
        fun readWgSnapshot(): Snapshot?
        fun networkType(): String
        fun carrier(): String
        fun serverSlot(): String
        suspend fun probeTunnelRttMs(): Double?
        suspend fun sendReport(json: JSONObject, ageSec: Int): Boolean
    }

    private val queue = ConcurrentLinkedQueue<Pending>()
    private val sampleMutex = Mutex()
    private var job: Job? = null
    @Volatile private var boundHost: Host? = null
    private var lastRx = -1L
    private var lastTx = -1L
    private var lastAtMs = 0L
    private var consecutiveProblems = 0

    fun isRunning(): Boolean = job?.isActive == true

    fun bindHost(host: Host) {
        boundHost = host
    }

    fun start(context: Context, scope: CoroutineScope, host: Host) {
        if (!BuildConfig.DEBUG) return
        stop()
        boundHost = host
        if (!host.isEnabled()) {
            DebugLog.d(TAG, "skip: not admin debug")
            return
        }
        DebugLog.i(TAG, "start → ${QualityLogStore.absolutePathHint(context)}")
        job = scope.launch {
            consecutiveProblems = 0
            // База сразу — первый вердикт через ~60с, не через 120с.
            host.readWgSnapshot()?.let { snap ->
                lastRx = snap.rxBytes
                lastTx = snap.txBytes
                lastAtMs = System.currentTimeMillis()
            } ?: run {
                lastRx = -1L
                lastTx = -1L
                lastAtMs = 0L
            }
            while (isActive) {
                delay(SAMPLE_MS)
                if (!host.isEnabled() || !host.isVpnUp()) continue
                sampleOnce(context, host, note = "periodic")
                flushQueue(host)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        consecutiveProblems = 0
    }

    fun flush(scope: CoroutineScope, host: Host) {
        if (!BuildConfig.DEBUG || !host.isEnabled()) return
        boundHost = host
        scope.launch { flushQueue(host) }
    }

    /**
     * Кнопка Quality: короткий замер (окно ~4с) + RTT → вердикт в файл.
     * Не probe — реальная оценка сети.
     */
    suspend fun measureNow(
        context: Context,
        host: Host? = boundHost,
        windowMs: Long = MANUAL_WINDOW_MS,
    ): MeasureResult {
        if (!BuildConfig.DEBUG) {
            return MeasureResult(false, "disabled", "только debug", "", "")
        }
        val h = host ?: boundHost
        if (h == null) {
            return MeasureResult(
                false,
                "no_host",
                "Нет host замера (баг UI)",
                QualityLogStore.absolutePathHint(context),
                "",
            )
        }
        // Ручной замер: достаточно VPN. is_admin нужен только фоновому монитору/серверу.
        if (!h.isVpnUp()) {
            return MeasureResult(false, "vpn_down", "VPN не подключён", "", "")
        }
        return sampleMutex.withLock {
            val s1 = h.readWgSnapshot()
                ?: return@withLock MeasureResult(false, "no_wg", "нет WG snapshot", "", "")
            delay(windowMs.coerceIn(1_000L, 15_000L))
            if (!h.isVpnUp()) {
                return@withLock MeasureResult(false, "vpn_down", "VPN отключился во время замера", "", "")
            }
            val s2 = h.readWgSnapshot()
                ?: return@withLock MeasureResult(false, "no_wg", "нет WG snapshot", "", "")
            val elapsed = windowMs.coerceAtLeast(1L)
            val rxDelta = (s2.rxBytes - s1.rxBytes).coerceAtLeast(0L)
            val txDelta = (s2.txBytes - s1.txBytes).coerceAtLeast(0L)
            val rtt = h.probeTunnelRttMs()
            val evaluated = QualityMonitorPolicy.evaluate(
                QualityMonitorPolicy.SampleInput(
                    elapsedMs = elapsed,
                    rxDelta = rxDelta,
                    txDelta = txDelta,
                    handshakeAgeSec = s2.handshakeAgeSec,
                    tunnelRttMs = rtt,
                    tunnelApiOk = rtt != null,
                ),
            )
            lastRx = s2.rxBytes
            lastTx = s2.txBytes
            lastAtMs = System.currentTimeMillis()
            val row = buildRow(
                host = h,
                evaluated = evaluated,
                rxDelta = rxDelta,
                txDelta = txDelta,
                elapsedMs = elapsed,
                handshakeAgeSec = s2.handshakeAgeSec,
                rtt = rtt,
                escalate = false,
                note = "manual_quality_button",
            )
            if (rtt == null) {
                row.put("probe_hint", "vpn_network_http_failed")
            }
            val written = QualityLogStore.append(context, row)
            maybeSend(context, h, evaluated, row)
            val summary =
                "${evaluated.verdict.name.lowercase()} ↓${round3(evaluated.downMbps)} ↑${round3(evaluated.upMbps)} " +
                    "rtt=${rtt?.let { "${it.toInt()}ms" } ?: "fail"}"
            MeasureResult(
                ok = written,
                verdict = evaluated.verdict.name.lowercase(),
                summary = if (written) "Quality: $summary" else "Quality: не записалось ($summary)",
                path = QualityLogStore.absolutePathHint(context),
                rowJson = row.toString(),
            )
        }
    }

    private suspend fun sampleOnce(context: Context, host: Host, note: String) {
        sampleMutex.withLock {
            val snap = host.readWgSnapshot() ?: return@withLock
            val now = System.currentTimeMillis()
            if (lastAtMs <= 0L || lastRx < 0L) {
                lastRx = snap.rxBytes
                lastTx = snap.txBytes
                lastAtMs = now
                return@withLock
            }
            val elapsed = (now - lastAtMs).coerceAtLeast(1L)
            val rxDelta = (snap.rxBytes - lastRx).coerceAtLeast(0L)
            val txDelta = (snap.txBytes - lastTx).coerceAtLeast(0L)
            lastRx = snap.rxBytes
            lastTx = snap.txBytes
            lastAtMs = now

            val rtt = host.probeTunnelRttMs()
            val evaluated = QualityMonitorPolicy.evaluate(
                QualityMonitorPolicy.SampleInput(
                    elapsedMs = elapsed,
                    rxDelta = rxDelta,
                    txDelta = txDelta,
                    handshakeAgeSec = snap.handshakeAgeSec,
                    tunnelRttMs = rtt,
                    tunnelApiOk = rtt != null,
                ),
            )

            if (QualityMonitorPolicy.isProblem(evaluated.verdict)) {
                consecutiveProblems += 1
            } else if (evaluated.verdict != QualityMonitorPolicy.Verdict.IDLE) {
                consecutiveProblems = 0
            }

            val escalate = QualityMonitorPolicy.shouldEscalate(consecutiveProblems)
            val row = buildRow(
                host = host,
                evaluated = evaluated,
                rxDelta = rxDelta,
                txDelta = txDelta,
                elapsedMs = elapsed,
                handshakeAgeSec = snap.handshakeAgeSec,
                rtt = rtt,
                escalate = escalate,
                note = note,
            )
            QualityLogStore.append(context, row)
            DebugLog.i(
                TAG,
                "$note ${evaluated.verdict} ↓${round3(evaluated.downMbps)} ↑${round3(evaluated.upMbps)} rtt=$rtt",
            )
            maybeSend(context, host, evaluated, row)
        }
    }

    private fun buildRow(
        host: Host,
        evaluated: QualityMonitorPolicy.SampleResult,
        rxDelta: Long,
        txDelta: Long,
        elapsedMs: Long,
        handshakeAgeSec: Long?,
        rtt: Double?,
        escalate: Boolean,
        note: String,
    ): JSONObject = JSONObject()
        .put("ts", QualityLogStore.utcIsoNow())
        .put("verdict", evaluated.verdict.name.lowercase())
        .put("likely_cause", evaluated.likelyCause)
        .put("down_mbps", round3(evaluated.downMbps))
        .put("up_mbps", round3(evaluated.upMbps))
        .put("rx_delta", rxDelta)
        .put("tx_delta", txDelta)
        .put("elapsed_ms", elapsedMs)
        .put("handshake_age_sec", handshakeAgeSec ?: JSONObject.NULL)
        .put("tunnel_rtt_ms", rtt ?: JSONObject.NULL)
        .put("network_type", host.networkType())
        .put("carrier", host.carrier())
        .put("server_slot", host.serverSlot())
        .put("app_version", BuildConfig.VERSION_NAME)
        .put("platform", "android")
        .put("debug", true)
        .put("escalate", escalate)
        .put("sent", false)
        .put("note", note)

    private suspend fun maybeSend(
        context: Context,
        host: Host,
        evaluated: QualityMonitorPolicy.SampleResult,
        row: JSONObject,
    ) {
        val escalate = row.optBoolean("escalate", false)
        if (!escalate && evaluated.verdict != QualityMonitorPolicy.Verdict.TUNNEL_API_FAIL) {
            return
        }
        DebugLog.w(TAG, "escalate ${evaluated.verdict} ${evaluated.likelyCause}")
        val ok = host.sendReport(row, 0)
        if (ok) {
            row.put("sent", true)
            QualityLogStore.append(context, JSONObject(row.toString()).put("note", "sent_ok"))
        } else {
            enqueue(row)
        }
    }

    private fun enqueue(row: JSONObject) {
        while (queue.size >= MAX_QUEUE) queue.poll()
        queue.offer(Pending(System.currentTimeMillis(), JSONObject(row.toString())))
    }

    private suspend fun flushQueue(host: Host) {
        if (!host.isVpnUp()) return
        val left = ArrayList<Pending>()
        while (true) {
            val p = queue.poll() ?: break
            val ageSec = ((System.currentTimeMillis() - p.atMs) / 1000L).toInt().coerceAtLeast(0)
            if (ageSec > 48 * 3600) continue
            p.attempts += 1
            val ok = runCatching { host.sendReport(p.body, ageSec) }.getOrDefault(false)
            if (!ok && p.attempts < 6) left.add(p)
        }
        left.forEach { queue.offer(it) }
    }

    private fun round3(v: Double): Double = (Math.round(v * 1000.0) / 1000.0)
}
