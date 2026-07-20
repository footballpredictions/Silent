package com.silent.vpn.ui.components

import android.graphics.BitmapFactory
import android.util.Log
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

private const val TAG = "HomeBgImage"
private const val THEME_ASSET_PUBLIC_BASE = "https://132-243-234-162.nip.io"

private val homeBgHttp = OkHttpClient.Builder()
    .connectTimeout(12, TimeUnit.SECONDS)
    .readTimeout(20, TimeUnit.SECONDS)
    .followRedirects(true)
    .build()

/** Grayscale muted home background (no blur) — matches PC/admin preview. */
@Composable
fun HomeBgImage(
    url: String,
    dark: Boolean,
    modifier: Modifier = Modifier,
) {
    var bitmap by remember(url) { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(url) {
        if (url.isBlank()) {
            bitmap = null
            return@LaunchedEffect
        }
        bitmap = withContext(Dispatchers.IO) {
            runCatching {
                val req = Request.Builder()
                    .url(url)
                    .header("Accept", "image/*,*/*")
                    .get()
                    .build()
                homeBgHttp.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        Log.w(TAG, "HTTP ${resp.code} for $url")
                        return@runCatching null
                    }
                    val bytes = resp.body?.bytes() ?: return@runCatching null
                    val opts = BitmapFactory.Options().apply {
                        inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888
                    }
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts).also {
                        if (it == null) Log.w(TAG, "decode failed (${bytes.size} bytes) $url")
                        else Log.i(TAG, "loaded ${it.width}x${it.height} from $url")
                    }
                }
            }.onFailure { e ->
                Log.w(TAG, "load failed $url: ${e.message}")
            }.getOrNull()
        }
    }
    val bmp = bitmap ?: return
    val saturation = ColorMatrix().apply { setToSaturation(0f) }
    Image(
        bitmap = bmp.asImageBitmap(),
        contentDescription = null,
        contentScale = ContentScale.Crop,
        colorFilter = ColorFilter.colorMatrix(saturation),
        // Чуть заметнее, чем 0.18 — иначе на светлом фоне «как будто нет»
        alpha = if (dark) 0.38f else 0.32f,
        modifier = modifier.fillMaxSize(),
    )
}

/**
 * Absolute URL for theme assets. Always nip.io — TLS cert is for that host, not raw IP.
 * BitmapFactory cannot decode SVG — callers should skip .svg for Android Image.
 */
fun resolveThemeAssetUrl(path: String?, apiBase: String = THEME_ASSET_PUBLIC_BASE): String {
    var raw = path?.trim().orEmpty()
    if (raw.isEmpty()) return ""
    val q = raw.indexOf('?')
    val pathOnly = if (q >= 0) raw.substring(0, q) else raw
    val query = if (q >= 0) raw.substring(q) else ""

    if (pathOnly.startsWith("data:", ignoreCase = true) ||
        pathOnly.startsWith("blob:", ignoreCase = true)
    ) {
        return raw
    }
    if (pathOnly.startsWith("http://", ignoreCase = true) ||
        pathOnly.startsWith("https://", ignoreCase = true)
    ) {
        return try {
            val u = java.net.URI(pathOnly)
            val host = u.host ?: return raw
            if (host == "132.243.234.162" || host == "132-243-234-162.nip.io") {
                val pathPart = u.path ?: "/"
                "$THEME_ASSET_PUBLIC_BASE$pathPart$query"
            } else {
                raw
            }
        } catch (_: Exception) {
            raw
        }
    }
    val rel = if (pathOnly.startsWith("/")) pathOnly else "/$pathOnly"
    return "$THEME_ASSET_PUBLIC_BASE$rel$query"
}

/** True if Android BitmapFactory can load this URL (not SVG). */
fun isRasterThemeAsset(url: String): Boolean {
    val path = url.substringBefore('?').lowercase()
    return !path.endsWith(".svg")
}
