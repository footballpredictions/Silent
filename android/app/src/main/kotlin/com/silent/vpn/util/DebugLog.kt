package com.silent.vpn.util

import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Временный буфер логов для отладки VPN — копирование из UI. */
object DebugLog {
    private const val MAX_LINES = 600
    private val _text = MutableStateFlow("")
    val text: StateFlow<String> = _text.asStateFlow()

    private val timeFmt = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
    private val buffer = ArrayDeque<String>(MAX_LINES + 1)

    @Synchronized
    private fun append(level: String, tag: String, msg: String) {
        val line = "${timeFmt.format(Date())} $level/$tag: $msg"
        buffer.addLast(line)
        while (buffer.size > MAX_LINES) buffer.removeFirst()
        _text.value = buffer.joinToString("\n")
    }

    fun d(tag: String, msg: String) {
        Log.d(tag, msg)
        append("D", tag, msg)
    }

    fun i(tag: String, msg: String) {
        Log.i(tag, msg)
        append("I", tag, msg)
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg)
        append("W", tag, msg)
    }

    fun e(tag: String, msg: String, t: Throwable? = null) {
        val full = if (t != null) "$msg (${t.message})" else msg
        Log.e(tag, full, t)
        append("E", tag, full)
    }

    fun getText(): String = synchronized(this) { buffer.joinToString("\n") }

    fun clear() {
        synchronized(this) {
            buffer.clear()
            _text.value = ""
        }
    }
}
