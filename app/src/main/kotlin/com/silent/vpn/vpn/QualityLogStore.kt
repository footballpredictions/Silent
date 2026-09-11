package com.silent.vpn.vpn

import android.content.ContentUris
import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import com.silent.vpn.policy.QualityMonitorPolicy
import com.silent.vpn.util.DebugLog
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * Журнал качества (admin debug) → Download/SilentVPN/
 * Один файл на календарный день: quality-YYYYMMDD-HHmmss.jsonl
 * (время = момент первого создания; без копий MediaStore с одним DISPLAY_NAME).
 */
object QualityLogStore {
    private const val TAG = "QualityLog"
    private const val MAX_FILES = 14
    private const val MIME = "text/plain"
    private const val PREFS = "silent_quality_log"
    private const val KEY_DAY = "active_day"
    private const val KEY_NAME = "active_name"
    private const val KEY_URI = "active_uri"

    data class ProbeResult(
        val ok: Boolean,
        val path: String,
        val tail: String,
        val fileName: String,
    )

    fun dayStamp(): String = SimpleDateFormat("yyyyMMdd", Locale.US).format(Date())

    fun timeStamp(): String = SimpleDateFormat("HHmmss", Locale.US).format(Date())

    fun publicDir(): File =
        File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            QualityMonitorPolicy.PUBLIC_FOLDER,
        )

    /** Имя активного файла за сегодня (создаётся один раз с временем). */
    @Synchronized
    fun activeFileName(context: Context): String {
        val day = dayStamp()
        val prefs = prefs(context)
        if (prefs.getString(KEY_DAY, null) == day) {
            prefs.getString(KEY_NAME, null)?.takeIf { it.isNotBlank() }?.let { return it }
        }
        val name = QualityMonitorPolicy.qualityFileName(day, timeStamp())
        prefs.edit()
            .putString(KEY_DAY, day)
            .putString(KEY_NAME, name)
            .remove(KEY_URI)
            .apply()
        return name
    }

    fun todayFile(context: Context): File = File(publicDir(), activeFileName(context))

    @Synchronized
    fun append(context: Context, row: JSONObject): Boolean {
        return runCatching {
            pruneOld(context)
            val fileName = activeFileName(context)
            val line = row.toString() + "\n"
            var written = false
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                runCatching {
                    appendViaMediaStore(context, fileName, line)
                    written = true
                }.onFailure { e ->
                    DebugLog.w(TAG, "MediaStore write: ${e.message}")
                }
            }
            if (!written) {
                val f = File(publicDir(), fileName)
                f.parentFile?.mkdirs()
                f.appendText(line)
                written = true
            }
            DebugLog.i(TAG, "wrote ${absolutePathHint(context)}")
            written
        }.onFailure { e ->
            DebugLog.w(TAG, "write failed: ${e.message}")
        }.getOrDefault(false)
    }

    /** Кнопка Quality / старт монитора. */
    fun writeProbe(context: Context, note: String): ProbeResult {
        val ok = append(
            context,
            JSONObject()
                .put("ts", utcIsoNow())
                .put("verdict", "probe")
                .put("note", note)
                .put("platform", "android")
                .put("debug", true),
        )
        val name = activeFileName(context)
        val path = absolutePathHint(context)
        val tail = if (ok) {
            readTail(context).ifBlank { "(записано, чтение пусто)" }
        } else {
            "(ошибка записи)"
        }
        return ProbeResult(ok = ok, path = path, tail = tail, fileName = name)
    }

    fun absolutePathHint(context: Context): String {
        val f = todayFile(context)
        if (f.exists()) return f.absolutePath
        return QualityMonitorPolicy.publicPathHint(activeFileName(context))
    }

    fun readTail(context: Context, maxLines: Int = 40): String {
        val fileName = activeFileName(context)
        val fromFile = runCatching {
            val f = File(publicDir(), fileName)
            if (f.exists()) {
                f.readLines().takeLast(maxLines).joinToString("\n").ifBlank { "(пусто)" }
            } else {
                null
            }
        }.getOrNull()
        if (fromFile != null) return fromFile
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            return readTailViaMediaStore(context, fileName, maxLines)
                ?: "(файла ещё нет — нажмите Quality или подождите сэмпл)"
        }
        return "(файла ещё нет)"
    }

    fun utcIsoNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun rememberUri(context: Context, uri: Uri) {
        prefs(context).edit().putString(KEY_URI, uri.toString()).apply()
    }

    private fun rememberedUri(context: Context): Uri? {
        val day = dayStamp()
        val prefs = prefs(context)
        if (prefs.getString(KEY_DAY, null) != day) return null
        val raw = prefs.getString(KEY_URI, null)?.takeIf { it.isNotBlank() } ?: return null
        return runCatching { Uri.parse(raw) }.getOrNull()
    }

    private fun appendViaMediaStore(context: Context, fileName: String, line: String) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        var uri = rememberedUri(context)
        if (uri != null) {
            val stillThere = runCatching {
                resolver.query(uri, arrayOf(MediaStore.MediaColumns._ID), null, null, null)?.use { it.moveToFirst() }
                    ?: false
            }.getOrDefault(false)
            if (!stillThere || isPending(resolver, uri)) {
                if (uri != null && isPending(resolver, uri)) {
                    runCatching { resolver.delete(uri, null, null) }
                }
                prefs(context).edit().remove(KEY_URI).apply()
                uri = null
            }
        }
        if (uri == null) {
            uri = findDownloadUri(resolver, collection, fileName)
        }
        if (uri != null && isPending(resolver, uri)) {
            DebugLog.w(TAG, "drop pending MediaStore row")
            runCatching { resolver.delete(uri, null, null) }
            uri = null
            prefs(context).edit().remove(KEY_URI).apply()
        }
        val bytes = line.toByteArray(Charsets.UTF_8)
        if (uri == null) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, MIME)
                put(
                    MediaStore.MediaColumns.RELATIVE_PATH,
                    Environment.DIRECTORY_DOWNLOADS + "/" + QualityMonitorPolicy.PUBLIC_FOLDER + "/",
                )
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            uri = resolver.insert(collection, values)
                ?: error("MediaStore insert failed for $fileName")
            try {
                resolver.openOutputStream(uri, "w")?.use { out ->
                    out.write(bytes)
                    out.flush()
                } ?: error("openOutputStream(w) failed")
            } catch (e: Exception) {
                runCatching { resolver.delete(uri, null, null) }
                throw e
            } finally {
                runCatching {
                    resolver.update(
                        uri,
                        ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                        null,
                        null,
                    )
                }
            }
            rememberUri(context, uri)
            return
        }
        rememberUri(context, uri)
        val appended = runCatching {
            resolver.openOutputStream(uri, "wa")?.use { out ->
                out.write(bytes)
                out.flush()
            } ?: error("null stream")
            true
        }.getOrDefault(false)
        if (!appended) {
            val prev = resolver.openInputStream(uri)?.use { it.readBytes() } ?: ByteArray(0)
            resolver.openOutputStream(uri, "rwt")?.use { out ->
                out.write(prev)
                out.write(bytes)
                out.flush()
            } ?: resolver.openOutputStream(uri, "wt")?.use { out ->
                out.write(prev)
                out.write(bytes)
                out.flush()
            } ?: error("MediaStore rewrite failed")
        }
    }

    private fun isPending(resolver: android.content.ContentResolver, uri: Uri): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return false
        resolver.query(
            uri,
            arrayOf(MediaStore.MediaColumns.IS_PENDING),
            null,
            null,
            null,
        )?.use { c ->
            if (c.moveToFirst()) return c.getInt(0) == 1
        }
        return false
    }

    private fun findDownloadUri(
        resolver: android.content.ContentResolver,
        collection: Uri,
        fileName: String,
    ): Uri? {
        val projection = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.RELATIVE_PATH,
        )
        for (rel in QualityMonitorPolicy.mediaStoreRelativePathCandidates()) {
            val sel =
                "${MediaStore.MediaColumns.DISPLAY_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=?"
            resolver.query(collection, projection, sel, arrayOf(fileName, rel), null)?.use { c ->
                if (c.moveToFirst()) {
                    return ContentUris.withAppendedId(collection, c.getLong(0))
                }
            }
        }
        val selName = "${MediaStore.MediaColumns.DISPLAY_NAME}=?"
        resolver.query(collection, projection, selName, arrayOf(fileName), null)?.use { c ->
            val idIdx = c.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
            val pathIdx = c.getColumnIndexOrThrow(MediaStore.MediaColumns.RELATIVE_PATH)
            while (c.moveToNext()) {
                val path = c.getString(pathIdx).orEmpty()
                if (path.contains(QualityMonitorPolicy.PUBLIC_FOLDER)) {
                    return ContentUris.withAppendedId(collection, c.getLong(idIdx))
                }
            }
        }
        return null
    }

    private fun readTailViaMediaStore(context: Context, fileName: String, maxLines: Int): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return null
        val resolver = context.contentResolver
        val uri = rememberedUri(context)
            ?: findDownloadUri(
                resolver,
                MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY),
                fileName,
            )
            ?: return null
        return resolver.openInputStream(uri)?.bufferedReader()?.use { reader ->
            reader.readLines().takeLast(maxLines).joinToString("\n").ifBlank { "(пусто)" }
        }
    }

    private fun pruneOld(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            pruneOldMediaStore(context)
        }
        val files = publicDir().listFiles()
            ?.filter { it.name.startsWith("quality-") && it.name.endsWith(".jsonl") }
            ?: return
        if (files.size <= MAX_FILES) return
        files.sortedBy { it.name }.dropLast(MAX_FILES).forEach { it.delete() }
    }

    private fun pruneOldMediaStore(context: Context) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val projection = arrayOf(
            MediaStore.MediaColumns._ID,
            MediaStore.MediaColumns.DISPLAY_NAME,
        )
        val names = mutableListOf<Pair<Long, String>>()
        resolver.query(
            collection,
            projection,
            "${MediaStore.MediaColumns.DISPLAY_NAME} LIKE ?",
            arrayOf("quality-%.jsonl"),
            null,
        )?.use { c ->
            val idIdx = c.getColumnIndexOrThrow(MediaStore.MediaColumns._ID)
            val nameIdx = c.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME)
            while (c.moveToNext()) {
                names += c.getLong(idIdx) to c.getString(nameIdx)
            }
        }
        if (names.size <= MAX_FILES) return
        names.sortedBy { it.second }.dropLast(MAX_FILES).forEach { (id, _) ->
            runCatching {
                resolver.delete(ContentUris.withAppendedId(collection, id), null, null)
            }
        }
    }
}
