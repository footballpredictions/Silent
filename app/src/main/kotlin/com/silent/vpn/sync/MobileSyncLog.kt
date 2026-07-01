package com.silent.vpn.sync

import android.util.Log
import com.silent.vpn.util.DebugLog

/**
 * Единый тег для отладки sync на LTE через adb:
 * adb logcat -s MobileSync
 */
object MobileSyncLog {
    const val TAG = "MobileSync"

    fun i(step: String, msg: String) {
        Log.i(TAG, "[$step] $msg")
        DebugLog.i(TAG, "[$step] $msg")
    }

    fun w(step: String, msg: String) {
        Log.w(TAG, "[$step] $msg")
        DebugLog.w(TAG, "[$step] $msg")
    }

    fun e(step: String, msg: String, t: Throwable? = null) {
        Log.e(TAG, "[$step] $msg", t)
        DebugLog.e(TAG, "[$step] $msg${t?.let { ": ${it.message}" } ?: ""}")
    }
}
