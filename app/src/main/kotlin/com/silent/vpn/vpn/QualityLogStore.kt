package com.silent.vpn.vpn

import android.content.Context
import com.silent.vpn.util.DebugLog
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Локальный журнал качества VPN (admin debug).
 * Путь: Android/data/…/files/silent-quality/quality-YYYYMMDD.jsonl
 * Можно снять через adb, если до сервера так и не достучались.
 */
object QualityLogStore {
    private const val TAG = "QualityLog"
    private const val DIR = "silent-quality"
    private const val MAX_DAYS = 7

    fun dir(context: Context): File {
        val base = context.getExternalFilesDir(null) ?: context.filesDir
        return File(base, DIR).also { it.mkdirs() }
    }

    fun todayFile(context: Context): File {
        val day = SimpleDateFormat("yyyyMMdd", Locale.US).format(Date())
        return File(dir(context), "quality-$day.jsonl")
    }

    @Synchronized
    fun append(context: Context, row: JSONObject) {
        runCatching {
            pruneOld(context)
            val f = todayFile(context)
            f.appendText(row.toString() + "\n")
            DebugLog.i(TAG, "wrote ${f.name} (${f.length()} B)")
        }.onFailure { e ->
            DebugLog.w(TAG, "write failed: ${e.message}")
        }
    }

    fun absolutePathHint(context: Context): String = todayFile(context).absolutePath

    private fun pruneOld(context: Context) {
        val files = dir(context).listFiles()?.filter { it.name.startsWith("quality-") && it.name.endsWith(".jsonl") }
            ?: return
        if (files.size <= MAX_DAYS) return
        files.sortedBy { it.name }.dropLast(MAX_DAYS).forEach { it.delete() }
    }

    fun utcIsoNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }
}
