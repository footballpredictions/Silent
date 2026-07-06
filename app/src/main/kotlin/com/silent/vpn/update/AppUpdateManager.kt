package com.silent.vpn.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.core.content.FileProvider
import com.silent.vpn.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.util.concurrent.TimeUnit

object AppUpdateManager {

    fun currentVersion(): String = BuildConfig.VERSION_NAME

    suspend fun downloadApk(
        context: Context,
        url: String,
        filename: String,
        client: OkHttpClient,
        onProgress: (Int) -> Unit,
    ): File = withContext(Dispatchers.IO) {
        val dir = File(context.cacheDir, "updates").apply { mkdirs() }
        dir.listFiles()?.forEach { it.delete() }
        val dest = File(dir, filename.ifBlank { "update.apk" })
        val tmp = File(dir, "${dest.name}.part")
        if (tmp.exists()) tmp.delete()

        val request = Request.Builder().url(url).build()
        withContext(Dispatchers.Main) { onProgress(0) }
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IllegalStateException("HTTP ${response.code}")
            val body = response.body ?: throw IllegalStateException("Empty body")
            val total = body.contentLength()
            var received = 0L
            var lastPct = -1
            var lastIndeterminateBump = 0L
            body.byteStream().use { input ->
                tmp.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        output.write(buf, 0, n)
                        received += n
                        if (total > 0) {
                            val pct = ((received * 100) / total).toInt().coerceIn(0, 100)
                            if (pct != lastPct) {
                                lastPct = pct
                                withContext(Dispatchers.Main) { onProgress(pct) }
                            }
                            if (received >= total) break
                        } else if (received - lastIndeterminateBump >= 256 * 1024) {
                            lastIndeterminateBump = received
                            val pct = (lastPct.coerceAtLeast(1) + 1).coerceAtMost(99)
                            lastPct = pct
                            withContext(Dispatchers.Main) { onProgress(pct) }
                        } else if (received > 0 && lastPct < 1) {
                            lastPct = 1
                            withContext(Dispatchers.Main) { onProgress(1) }
                        }
                    }
                    output.flush()
                }
            }
            if (total > 0 && received < total) {
                throw IllegalStateException("Incomplete download: $received/$total")
            }
        }
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
