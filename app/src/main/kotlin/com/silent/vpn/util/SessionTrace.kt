package com.silent.vpn.util

import android.os.Looper
import android.util.Log

/**
 * Трассировка узлов VPN / плитки QS для logcat.
 * Log.e — не вырезается R8 в release. TAG в тексте — для поиска в Android Studio.
 *
 *   tag:SilentTrace
 */
object SessionTrace {
    const val TAG = "SilentTrace"

    fun enter(node: String, detail: String = "") = log(">>>", node, detail)
    fun exit(node: String, detail: String = "") = log("<<<", node, detail)
    fun mark(node: String, detail: String = "") = log("---", node, detail)
    fun wait(node: String, detail: String = "") = log("...", node, detail)

    fun warn(node: String, detail: String) = log("!!!", node, detail)

    private fun log(prefix: String, node: String, detail: String) {
        val thread = if (Looper.myLooper() == Looper.getMainLooper()) "main" else Thread.currentThread().name
        val body = if (detail.isEmpty()) node else "$node | $detail"
        val msg = "$TAG $prefix [$thread] $body"
        Log.e(TAG, msg)
        DebugLog.traceUi(TAG, msg)
    }
}
