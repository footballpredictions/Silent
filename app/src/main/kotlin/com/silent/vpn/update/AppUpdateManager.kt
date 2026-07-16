package com.silent.vpn.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import com.silent.vpn.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File

object AppUpdateManager {

    fun currentVersion(): String = BuildConfig.VERSION_NAME

    /**
     * Скачать APK. [expectedSize] — размер из `/api/updates/check` (fallback, если нет Content-Length).
     * Прогресс пишется с IO-потока (StateFlow thread-safe); без hop на Main на каждый chunk —
     * на Android 11–12 hop в цикле чтения часто оставляет UI на 0% до конца загрузки.
     */
    suspend fun downloadApk(
        context: Context,
        url: String,
        filename: String,
        client: OkHttpClient,
        expectedSize: Long = 0L,
        onProgress: (Int) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val dest = File(dir, filename.ifBlank { "update.apk" })
        val tmp = File(dir, "${dest.name}.part")
        if (tmp.exists()) tmp.delete()

        val request = Request.Builder().url(url).build()
        onProgress(0)
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("HTTP ${response.code}")
            val body = response.body ?: throw IllegalStateException("Empty body")
            val total = DownloadProgress.resolveTotal(body.contentLength(), expectedSize)
            var received = 0L
            var lastPct = -1
            var lastEmitAtMs = 0L
            body.byteStream().use { input ->
                tmp.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        output.write(buf, 0, n)
                        received += n
                        val pct = DownloadProgress.percent(received, total)
                        val now = System.currentTimeMillis()
                        val shouldEmit = pct != lastPct && (
                            pct >= 100 ||
                                lastPct < 0 ||
                                pct == 1 ||
                                now - lastEmitAtMs >= 120L
                            )
                        if (shouldEmit) {
                            lastPct = pct
                            lastEmitAtMs = now
                            onProgress(pct)
                        }
                        if (total > 0 && received >= total) break
                    }
                    output.flush()
                }
            }
            if (total > 0 && received < total) {
                throw IllegalStateException("Incomplete download: $received/$total")
            }
        }
        onProgress(100)
        if (dest.exists()) dest.delete()
        if (!tmp.renameTo(dest)) {
            tmp.copyTo(dest, overwrite = true)
            tmp.delete()
        }
        dest
    }

    fun installApk(context: Context, apkFile: File, fromActivity: Boolean = false): Intent {
        val uri: Uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            apkFile,
        )
        return Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            if (!fromActivity) addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
}

/** Чистая логика процентов — удобно покрывать юнит-тестами. */
object DownloadProgress {
    private const val FALLBACK_ESTIMATE_BYTES = 50L * 1024L * 1024L

    fun resolveTotal(contentLength: Long, expectedSize: Long): Long = when {
        contentLength > 0L -> contentLength
        expectedSize > 0L -> expectedSize
        else -> -1L
    }

    /**
     * @param total > 0 — реальный/ожидаемый размер; иначе оценка до 95% по объёму байт.
     */
    fun percent(received: Long, total: Long): Int {
        if (received <= 0L) return 0
        if (total > 0L) {
            return ((received * 100L) / total).toInt().coerceIn(0, 100)
        }
        val pct = ((received * 95L) / FALLBACK_ESTIMATE_BYTES).toInt()
        return pct.coerceIn(1, 95)
    }
}
