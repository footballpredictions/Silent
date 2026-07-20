package com.silent.vpn.ui.components

import android.graphics.BitmapFactory
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

private val homeBgHttp = OkHttpClient.Builder()
    .connectTimeout(8, TimeUnit.SECONDS)
    .readTimeout(12, TimeUnit.SECONDS)
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
                val req = Request.Builder().url(url).get().build()
                homeBgHttp.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@runCatching null
                    val bytes = resp.body?.bytes() ?: return@runCatching null
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                }
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
        alpha = if (dark) 0.22f else 0.18f,
        modifier = modifier.fillMaxSize(),
    )
}

fun resolveThemeAssetUrl(path: String?, apiBase: String): String {
    val raw = path?.trim().orEmpty()
    if (raw.isEmpty()) return ""
    if (raw.startsWith("http://", ignoreCase = true) ||
        raw.startsWith("https://", ignoreCase = true) ||
        raw.startsWith("data:", ignoreCase = true)
    ) {
        return raw
    }
    val base = apiBase.trimEnd('/')
    if (base.isEmpty()) return raw
    return if (raw.startsWith("/")) "$base$raw" else "$base/$raw"
}
