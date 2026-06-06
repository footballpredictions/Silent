package com.silent.vpn.vpn

import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Отправка сбоев хеша на backend (debounce 5 мин на пару hash+type).
 * Устанавливается из MainViewModel при старте приложения.
 */
object HashFailureReporter {
    private const val TAG = "HashFailureReporter"
    private const val DEBOUNCE_MS = 5 * 60 * 1000L

    private val lastReportMs = mutableMapOf<String, Long>()
    private var reportFn: (suspend (hash: String, errorType: String, message: String) -> Unit)? = null

    fun install(fn: suspend (hash: String, errorType: String, message: String) -> Unit) {
        reportFn = fn
    }

    fun reset() {
        lastReportMs.clear()
    }

    fun report(scope: CoroutineScope, hashHint: String, errorType: String, message: String) {
        val hash = hashHint.trim()
        if (hash.length < 6) return
        val type = errorType.trim().ifBlank { "unknown" }
        val key = "${hash.take(32)}|$type"
        val now = System.currentTimeMillis()
        synchronized(lastReportMs) {
            if (now - (lastReportMs[key] ?: 0L) < DEBOUNCE_MS) return
            lastReportMs[key] = now
        }
        val fn = reportFn ?: return
        scope.launch {
            runCatching { fn(hash, type, message.take(500)) }
                .onFailure { e -> DebugLog.w(TAG, "report failed: ${e.message}") }
        }
    }
}
