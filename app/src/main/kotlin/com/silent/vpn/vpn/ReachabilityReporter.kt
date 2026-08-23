package com.silent.vpn.vpn

import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentLinkedQueue

/**
 * Репорт агенту доступности: на какой стадии сорвалось подключение.
 *
 * Отказ обычно и означает, что отправить сразу не получилось, поэтому репорт
 * кладётся в очередь и уходит, когда канал до API появится (main VPN, соты :9100
 * или bootstrap-туннель). Возраст репорта считается по времени самого отказа,
 * иначе отложенная пачка легла бы в текущее окно и агент увидел бы блокировку,
 * которой уже нет.
 */
object ReachabilityReporter {
    private const val TAG = "ReachabilityReporter"
    private const val DEBOUNCE_MS = 5 * 60 * 1000L
    /** Дольше сервер репорт не хранит и отвечает `stale`. */
    private const val MAX_AGE_MS = 48L * 60 * 60 * 1000
    private const val MAX_QUEUE = 40
    private const val MAX_ATTEMPTS = 6

    const val STAGE_HANDSHAKE = "handshake"
    const val STAGE_TUNNEL_DEAD = "tunnel_dead"
    const val STAGE_API = "api"

    data class Pending(
        val stage: String,
        val atMs: Long,
        val tunnelUptimeSec: Int?,
        val detail: String,
        var attempts: Int = 0,
    )

    private val lastReportMs = mutableMapOf<String, Long>()
    private val queue = ConcurrentLinkedQueue<Pending>()
    private var sendFn: (suspend (Pending, ageSec: Int) -> Boolean)? = null

    /** [fn] возвращает true, если репорт доставлен. */
    fun install(fn: suspend (Pending, Int) -> Boolean) {
        sendFn = fn
    }

    fun reset() {
        synchronized(lastReportMs) { lastReportMs.clear() }
        queue.clear()
    }

    fun pendingCount(): Int = queue.size

    fun report(
        scope: CoroutineScope,
        stage: String,
        tunnelUptimeSec: Int? = null,
        detail: String = "",
    ) {
        val now = System.currentTimeMillis()
        synchronized(lastReportMs) {
            if (now - (lastReportMs[stage] ?: 0L) < DEBOUNCE_MS) return
            lastReportMs[stage] = now
        }
        val item = Pending(
            stage = stage,
            atMs = now,
            tunnelUptimeSec = tunnelUptimeSec,
            detail = detail.take(400),
        )
        val fn = sendFn
        if (fn == null) {
            enqueue(item)
            return
        }
        scope.launch {
            val ok = runCatching { fn(item, 0) }.getOrDefault(false)
            if (!ok) {
                item.attempts = 1
                enqueue(item)
                DebugLog.i(TAG, "$stage в очереди (${queue.size})")
            } else {
                DebugLog.i(TAG, "$stage отправлен")
            }
        }
    }

    private fun enqueue(item: Pending) {
        queue.add(item)
        while (queue.size > MAX_QUEUE) queue.poll()
    }

    /** Вызывать, когда канал до API подтвердился: туннель поднялся или Wi‑Fi tick. */
    fun flush(scope: CoroutineScope) {
        if (queue.isEmpty()) return
        val fn = sendFn ?: return
        scope.launch {
            val now = System.currentTimeMillis()
            val batch = mutableListOf<Pending>()
            while (true) {
                val item = queue.poll() ?: break
                batch.add(item)
            }
            for (item in batch) {
                if (now - item.atMs > MAX_AGE_MS || item.attempts >= MAX_ATTEMPTS) continue
                val ageSec = ((now - item.atMs) / 1000).coerceAtLeast(0).toInt()
                val ok = runCatching { fn(item, ageSec) }.getOrDefault(false)
                if (!ok) {
                    item.attempts += 1
                    enqueue(item)
                }
            }
        }
    }
}
