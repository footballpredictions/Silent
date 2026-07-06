package com.silent.vpn.util

import android.util.Log
import com.silent.vpn.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Буфер логов для UI «Лог»; в release не копим каждую строку libclient (CPU/нагрев). */
object DebugLog {
    private const val MAX_LINES = 600
    private const val UI_FLUSH_MS = 1_500L
    private val _text = MutableStateFlow("")
    val text: StateFlow<String> = _text.asStateFlow()

    private val timeFmt = SimpleDateFormat("HH:mm:ss.SSS", Locale.US)
    private val buffer = ArrayDeque<String>(MAX_LINES + 1)
    private var lastUiFlushMs = 0L
    private var uiDirty = false

    @Synchronized
    private fun append(level: String, tag: String, msg: String, flushUi: Boolean) {
        val line = "${timeFmt.format(Date())} $level/$tag: $msg"
        buffer.addLast(line)
        while (buffer.size > MAX_LINES) buffer.removeFirst()
        if (!flushUi) return
        val now = System.currentTimeMillis()
        if (now - lastUiFlushMs >= UI_FLUSH_MS) {
            lastUiFlushMs = now
            uiDirty = false
            _text.value = buffer.joinToString("\n")
        } else {
            uiDirty = true
        }
    }

    @Synchronized
    private fun flushUiIfDirty() {
        if (!uiDirty) return
        lastUiFlushMs = System.currentTimeMillis()
        uiDirty = false
        _text.value = buffer.joinToString("\n")
    }

    /** Verbose — только debug; в release не трогаем UI-буфер. */
    fun d(tag: String, msg: String) {
        if (BuildConfig.DEBUG) {
            Log.d(tag, msg)
            append("D", tag, msg, flushUi = true)
        }
    }

    /** Важные события — всегда в буфер (статистика, overlay, ошибки connect). */
    fun i(tag: String, msg: String) {
        Log.i(tag, msg)
        append("I", tag, msg, flushUi = true)
        flushUiIfDirty()
    }

    fun w(tag: String, msg: String) {
        Log.w(tag, msg)
        append("W", tag, msg, flushUi = true)
        flushUiIfDirty()
    }

    fun e(tag: String, msg: String, t: Throwable? = null) {
        val full = if (t != null) "$msg (${t.message})" else msg
        Log.e(tag, full, t)
        append("E", tag, full, flushUi = true)
        flushUiIfDirty()
    }

    /** Только буфер UI «Лог», без второй строки в logcat. */
    fun traceUi(tag: String, msg: String) {
        append("T", tag, msg, flushUi = true)
        flushUiIfDirty()
    }

    fun getText(): String = synchronized(this) { buffer.joinToString("\n") }

    /** Сбросить отложенный UI-буфер (перед открытием диалога «Лог»). */
    fun flushAll() {
        synchronized(this) {
            lastUiFlushMs = System.currentTimeMillis()
            uiDirty = false
            _text.value = buffer.joinToString("\n")
        }
    }

    fun clear() {
        synchronized(this) {
            buffer.clear()
            uiDirty = false
            _text.value = ""
        }
    }
}
