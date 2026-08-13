package com.silent.vpn.util

import android.util.Log

/**
 * Единый тег Logcat для диагностики olcrtc2 (Telemost / WB).
 *
 * Android Studio → Logcat → фильтр:
 *   tag:SVPN_OLC
 * или package + tag:
 *   package:com.silent.vpn tag:SVPN_OLC
 *
 * Флаги в сообщении:
 *   [CFG]   — fetch/кеш/accept assign
 *   [CACHE] — чтение/запись/wipe слота
 *   [APPLY] — меню Применить / смена провайдера
 *   [CONN]  — connect / SOCKS / TUN / ready
 *   [LEAVE] — leave / teardown room
 *   [FAIL]  — room failure / reassign
 *   [HB]    — heartbeat
 *   [TM]    — Telemost-only
 *   [WB]    — WB-only
 *   [SESS]  — bind/clear session snapshot
 */
object OlcrtcDiag {
    const val TAG = "SVPN_OLC"

    const val CFG = "CFG"
    const val CACHE = "CACHE"
    const val APPLY = "APPLY"
    const val CONN = "CONN"
    const val LEAVE = "LEAVE"
    const val FAIL = "FAIL"
    const val HB = "HB"
    const val TM = "TM"
    const val WB = "WB"
    const val SESS = "SESS"
    const val TUN = "TUN"
    const val AUTH = "AUTH"

    fun i(flag: String, msg: String) {
        Log.i(TAG, "[$flag] $msg")
    }

    fun w(flag: String, msg: String) {
        Log.w(TAG, "[$flag] $msg")
    }

    fun e(flag: String, msg: String, t: Throwable? = null) {
        if (t != null) Log.e(TAG, "[$flag] $msg", t) else Log.e(TAG, "[$flag] $msg")
    }

    /** Зеркало UI-ключей olcrtc_* → SVPN_OLC. */
    fun fromUiKey(key: String, message: String, isError: Boolean) {
        val flag = when {
            key.contains("wb", ignoreCase = true) -> WB
            key.contains("tm", ignoreCase = true) ||
                key.contains("telemost", ignoreCase = true) -> TM
            key.contains("leave", ignoreCase = true) ||
                key.contains("stop", ignoreCase = true) -> LEAVE
            key.contains("fail", ignoreCase = true) ||
                key.contains("dead", ignoreCase = true) ||
                key.contains("health", ignoreCase = true) -> FAIL
            key.contains("auth", ignoreCase = true) -> AUTH
            key.contains("tun", ignoreCase = true) ||
                key.contains("hev", ignoreCase = true) -> TUN
            key.contains("ready", ignoreCase = true) ||
                key.contains("socks", ignoreCase = true) ||
                key.contains("dial", ignoreCase = true) ||
                key.contains("connect", ignoreCase = true) ||
                key.contains("ice", ignoreCase = true) ||
                key.contains("exec", ignoreCase = true) -> CONN
            else -> CONN
        }
        val line = "$key | $message"
        if (isError) w(flag, line) else i(flag, line)
    }
}
