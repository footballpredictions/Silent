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
import org.json.JSONObject
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Admin + debug only: пассивный мониторинг скорости туннеля.
 * Отчёты уходят только через VPN (tunnel API); параллельно пишется локальный файл.
 */
object QualityMonitor {
    private const val TAG = "QualityMonitor"
    private const val SAMPLE_MS = 60_000L
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

    interface Host {
        fun isEnabled(): Boolean
        fun isVpnUp(): Boolean
        fun readWgSnapshot(): Snapshot?
        fun networkType(): String
        fun carrier(): String
        fun serverSlot(): String
        /** RTT ms to tunnel API, or null if failed. */
        suspend fun probeTunnelRttMs(): Double?
        /** Send via VPN tunnel only. true = accepted. */
        suspend fun sendReport(json: JSONObject, ageSec: Int): Boolean
    }

    private val queue = ConcurrentLinkedQueue<Pending>()
    private var job: Job? = null
    private var lastRx = -1L
    private var lastTx = -1L
    private var lastAtMs = 0L
    private var consecutiveProblems = 0

    fun isRunning(): Boolean = job?.isActive == true

    fun start(context: Context, scope: CoroutineScope, host: Host) {
        if (!BuildConfig.DEBUG) return
        stop()
        if (!host.isEnabled()) {
            DebugLog.d(TAG, "skip: not admin debug")
            return
        }
        DebugLog.i(TAG, "start → ${QualityLogStore.absolutePathHint(context)}")
        job = scope.launch {
            lastRx = -1L
            lastTx = -1L
            lastAtMs = 0L
            consecutiveProblems = 0
            while (isActive) {
                delay(SAMPLE_MS)
                if (!host.isEnabled() || !host.isVpnUp()) continue
                sampleOnce(context, host)
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
        scope.launch { flushQueue(host) }
    }

    private suspend fun sampleOnce(context: Context, host: Host) {
        val snap = host.readWgSnapshot() ?: return
        val now = System.currentTimeMillis()
        if (lastAtMs <= 0L || lastRx < 0L) {
            lastRx = snap.rxBytes
            lastTx = snap.txBytes
            lastAtMs = now
            return
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
        val row = JSONObject()
            .put("ts", QualityLogStore.utcIsoNow())
            .put("verdict", evaluated.verdict.name.lowercase())
            .put("likely_cause", evaluated.likelyCause)
            .put("down_mbps", round3(evaluated.downMbps))
            .put("up_mbps", round3(evaluated.upMbps))
            .put("rx_delta", rxDelta)
            .put("tx_delta", txDelta)
            .put("elapsed_ms", elapsed)
            .put("handshake_age_sec", snap.handshakeAgeSec ?: JSONObject.NULL)
            .put("tunnel_rtt_ms", rtt ?: JSONObject.NULL)
            .put("network_type", host.networkType())
            .put("carrier", host.carrier())
            .put("server_slot", host.serverSlot())
            .put("app_version", BuildConfig.VERSION_NAME)
            .put("platform", "android")
            .put("debug", true)
            .put("escalate", escalate)
            .put("sent", false)

        if (escalate || evaluated.verdict == QualityMonitorPolicy.Verdict.TUNNEL_API_FAIL) {
            QualityLogStore.append(context, row)
            DebugLog.w(
                TAG,
                "problem ${evaluated.verdict} ↓${round3(evaluated.downMbps)} ↑${round3(evaluated.upMbps)} " +
                    "rtt=$rtt ${evaluated.likelyCause}",
            )
            val ok = host.sendReport(row, 0)
            if (ok) {
                row.put("sent", true)
                QualityLogStore.append(context, JSONObject(row.toString()).put("note", "sent_ok"))
            } else {
                enqueue(row)
            }
        } else {
            DebugLog.d(
                TAG,
                "${evaluated.verdict} ↓${round3(evaluated.downMbps)} ↑${round3(evaluated.upMbps)} rtt=$rtt",
            )
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
