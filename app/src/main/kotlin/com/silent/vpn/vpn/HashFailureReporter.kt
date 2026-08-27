package com.silent.vpn.vpn



import com.silent.vpn.util.DebugLog

import kotlinx.coroutines.CoroutineScope

import kotlinx.coroutines.launch



/**

 * Сбои хеша на backend (debounce 5 мин на пару hash+type).

 * Считаем: hash_dead / нет соединений; captcha — только если повторяется на том же хеше.

 */

object HashFailureReporter {

    private const val TAG = "HashFailureReporter"

    private const val DEBOUNCE_MS = 5 * 60 * 1000L

    private const val CAPTCHA_REPORT_THRESHOLD = 3

    private const val CAPTCHA_WINDOW_MS = 10 * 60 * 1000L



    private val lastReportMs = mutableMapOf<String, Long>()

    private val captchaHits = mutableMapOf<String, MutableList<Long>>()

    private var reportFn: (suspend (hash: String, errorType: String, message: String) -> Unit)? = null



    fun install(fn: suspend (hash: String, errorType: String, message: String) -> Unit) {

        reportFn = fn

    }



    fun reset() {

        lastReportMs.clear()

        captchaHits.clear()

    }



    fun report(scope: CoroutineScope, hashHint: String, errorType: String, message: String) {

        val hash = hashHint.trim()

        if (hash.length < 6) return



        var type = errorType.trim().ifBlank { "unknown" }

        val msg = message.take(500)



        if (isCaptchaRelated(msg) || type.contains("captcha", ignoreCase = true)) {

            if (!isPersistentCaptcha(hash)) return

            type = "captcha_persistent"

        } else if (isTransientHashError(msg) && type != "hash_dead" && type != "no_connections") {

            return

        }



        val key = "${hash.take(32)}|$type"

        val now = System.currentTimeMillis()

        synchronized(lastReportMs) {

            if (now - (lastReportMs[key] ?: 0L) < DEBOUNCE_MS) return

            lastReportMs[key] = now

        }

        val fn = reportFn ?: return

        scope.launch {

            runCatching { fn(hash, type, msg) }

                .onFailure { e -> DebugLog.w(TAG, "report failed: ${e.message}") }

        }

    }



    private fun isCaptchaRelated(message: String): Boolean {

        val m = message.lowercase()

        return m.contains("captcha") || m.contains("капч")

    }



    private fun isPersistentCaptcha(hash: String): Boolean {

        val now = System.currentTimeMillis()

        val key = hash.take(32)

        synchronized(captchaHits) {

            val hits = captchaHits.getOrPut(key) { mutableListOf() }

            hits.add(now)

            hits.removeAll { now - it > CAPTCHA_WINDOW_MS }

            return hits.size >= CAPTCHA_REPORT_THRESHOLD

        }

    }



    /** Сеть/VK временно — не «хеш сломан». hash_dead проходит. */

    private fun isTransientHashError(message: String): Boolean {

        val m = message.lowercase()

        if (m.isBlank()) return true

        if (m.contains("i/o timeout") || m.contains("context deadline")) return true

        if (m.contains("connection refused") || m.contains("connection reset")) return true

        if (m.contains("rate limit") || m.contains("flood control") || m.contains("error 29")) return true

        if (m.contains("getanonymoustoken") && m.contains("error 10")) return true

        if (m.contains("error 10") && m.contains("internal")) return true

        if (m.contains("timeout") && !m.contains("wrap_auth_timeout")) return true

        if (m.contains("all vk credentials failed")) return true

        if (m.contains("global lockout")) return true

        if (m.contains("anonym_token.outdated")) return true

        if (m.contains("anonym_token") && m.contains("outdated")) return true

        return false

    }

}


