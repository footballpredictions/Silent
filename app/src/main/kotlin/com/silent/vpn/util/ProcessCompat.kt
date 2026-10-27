package com.silent.vpn.util

import android.os.Build
import java.util.concurrent.TimeUnit

/** Process.isAlive/timed wait/forced destroy are absent from Android 7 (API 24/25). */
fun Process.isAliveCompat(): Boolean {
    if (Build.VERSION.SDK_INT >= 26) return isAlive
    return try {
        exitValue()
        false
    } catch (_: IllegalThreadStateException) {
        true
    }
}

fun Process.waitForCompat(timeout: Long, unit: TimeUnit): Boolean {
    if (Build.VERSION.SDK_INT >= 26) return waitFor(timeout, unit)
    val budget = unit.toNanos(timeout.coerceAtLeast(0))
    val start = System.nanoTime()
    while (isAliveCompat()) {
        val left = budget - (System.nanoTime() - start)
        if (left <= 0) return false
        TimeUnit.NANOSECONDS.sleep(minOf(left, TimeUnit.MILLISECONDS.toNanos(20)))
    }
    return true
}

fun Process.destroyForciblyCompat(): Process {
    if (Build.VERSION.SDK_INT >= 26) return destroyForcibly()
    destroy()
    return this
}
