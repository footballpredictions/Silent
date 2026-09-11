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
 * Локальный журнал качества VPN (admin debug).
 * Путь в общей памяти: Download/SilentVPN/quality-YYYYMMDD.jsonl
 * (Проводник / USB: «Загрузки» → SilentVPN — не Android/data/…).
 */
object QualityLogStore {
    private const val TAG = "QualityLog"
    private const val MAX_DAYS = 7
    private const val MIME = "application/x-ndjson"

    fun dayStamp(): String = SimpleDateFormat("yyyyMMdd", Locale.US).format(Date())

    fun todayFileName(): String = QualityMonitorPolicy.qualityFileName(dayStamp())

    /** Файл в Download/SilentVPN (для API&lt;29 и если MediaStore уже создал файл на диске). */
    fun todayFile(context: Context): File {
        val dir = publicDir()
        dir.mkdirs()
        return File(dir, todayFileName())
    }

    fun publicDir(): File =
        File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
            QualityMonitorPolicy.PUBLIC_FOLDER,
        )

    @Synchronized
    fun append(context: Context, row: JSONObject) {
        runCatching {
            pruneOld(context)
            val line = row.toString() + "\n"
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                appendViaMediaStore(context, todayFileName(), line)
            } else {
                val f = todayFile(context)
                f.parentFile?.mkdirs()
                f.appendText(line)
            }
            DebugLog.i(TAG, "wrote ${absolutePathHint(context)}")
        }.onFailure { e ->
            DebugLog.w(TAG, "write failed: ${e.message}")
        }
    }

    fun absolutePathHint(context: Context): String {
        val viaFile = todayFile(context)
        if (viaFile.exists()) return viaFile.absolutePath
        return QualityMonitorPolicy.publicPathHint(dayStamp())
    }

    /** Хвост файла для кнопки Quality в Debug Log. */
    fun readTail(context: Context, maxLines: Int = 40): String {
        val fromFile = runCatching {
            val f = todayFile(context)
            if (f.exists()) {
                f.readLines().takeLast(maxLines).joinToString("\n").ifBlank { "(пусто)" }
            } else {
                null
            }
        }.getOrNull()
        if (fromFile != null) return fromFile
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            return readTailViaMediaStore(context, todayFileName(), maxLines)
                ?: "(файла ещё нет)"
        }
        return "(файла ещё нет)"
    }

    fun utcIsoNow(): String {
        val fmt = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US)
        fmt.timeZone = TimeZone.getTimeZone("UTC")
        return fmt.format(Date())
    }

    private fun appendViaMediaStore(context: Context, fileName: String, line: String) {
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val relative = QualityMonitorPolicy.mediaStoreRelativePath()
        var uri = findDownloadUri(resolver, collection, fileName, relative)
        if (uri == null) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, MIME)
                put(MediaStore.MediaColumns.RELATIVE_PATH, relative)
                put(MediaStore.MediaColumns.IS_PENDING, 1)
            }
            uri = resolver.insert(collection, values)
                ?: error("MediaStore insert failed for $fileName")
            resolver.openOutputStream(uri, "w")?.use { out ->
                out.write(line.toByteArray(Charsets.UTF_8))
            } ?: error("openOutputStream failed")
            val done = ContentValues().apply {
                put(MediaStore.MediaColumns.IS_PENDING, 0)
            }
            resolver.update(uri, done, null, null)
        } else {
            resolver.openOutputStream(uri, "wa")?.use { out ->
                out.write(line.toByteArray(Charsets.UTF_8))
            } ?: error("openOutputStream append failed")
        }
    }

    private fun findDownloadUri(
        resolver: android.content.ContentResolver,
        collection: Uri,
        fileName: String,
        relativePath: String,
    ): Uri? {
        val projection = arrayOf(MediaStore.MediaColumns._ID)
        val sel =
            "${MediaStore.MediaColumns.DISPLAY_NAME}=? AND ${MediaStore.MediaColumns.RELATIVE_PATH}=?"
        resolver.query(collection, projection, sel, arrayOf(fileName, relativePath), null)?.use { c ->
            if (c.moveToFirst()) {
                val id = c.getLong(0)
                return ContentUris.withAppendedId(collection, id)
            }
        }
        // Некоторые OEM пишут RELATIVE_PATH без завершающего / или с Download/.
        val selName = "${MediaStore.MediaColumns.DISPLAY_NAME}=?"
        resolver.query(collection, projection, selName, arrayOf(fileName), null)?.use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0)
                return ContentUris.withAppendedId(collection, id)
            }
        }
        return null
    }

    private fun readTailViaMediaStore(context: Context, fileName: String, maxLines: Int): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return null
        val resolver = context.contentResolver
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val uri = findDownloadUri(
            resolver,
            collection,
            fileName,
            QualityMonitorPolicy.mediaStoreRelativePath(),
        ) ?: return null
        return resolver.openInputStream(uri)?.bufferedReader()?.use { reader ->
            reader.readLines().takeLast(maxLines).joinToString("\n").ifBlank { "(пусто)" }
        }
    }

    private fun pruneOld(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            pruneOldMediaStore(context)
            return
        }
        val files = publicDir().listFiles()
            ?.filter { it.name.startsWith("quality-") && it.name.endsWith(".jsonl") }
            ?: return
        if (files.size <= MAX_DAYS) return
        files.sortedBy { it.name }.dropLast(MAX_DAYS).forEach { it.delete() }
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
        if (names.size <= MAX_DAYS) return
        names.sortedBy { it.second }.dropLast(MAX_DAYS).forEach { (id, _) ->
            runCatching {
                resolver.delete(ContentUris.withAppendedId(collection, id), null, null)
            }
        }
    }
}
