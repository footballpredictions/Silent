package com.silent.vpn.ui.components

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.util.rememberIsTv
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

private val logoHttp = OkHttpClient.Builder()
    .connectTimeout(6, TimeUnit.SECONDS)
    .readTimeout(10, TimeUnit.SECONDS)
    .build()

/** Brand mark: black rounded square + white S. На TV чуть крупнее (чёткость), на phone — 56dp.
 *  Если [imageUrl] задан — загружает картинку с сервера (theme.logo_url). */
@Composable
fun SilentLogo(
    modifier: Modifier = Modifier,
    boxSize: Dp? = null,
    cornerRadius: Dp? = null,
    letterSize: TextUnit? = null,
    imageUrl: String? = null,
) {
    val isTv = rememberIsTv()
    val resolvedBox = boxSize ?: if (isTv) 72.dp else 56.dp
    val resolvedCorner = cornerRadius ?: if (isTv) 20.dp else 16.dp
    val resolvedLetter = letterSize ?: if (isTv) 28.sp else 22.sp
    val url = imageUrl?.trim().orEmpty()
    var remoteBmp by remember(url) { mutableStateOf<android.graphics.Bitmap?>(null) }
    var loadFailed by remember(url) { mutableStateOf(false) }

    LaunchedEffect(url) {
        if (url.isBlank()) {
            remoteBmp = null
            loadFailed = false
            return@LaunchedEffect
        }
        loadFailed = false
        remoteBmp = withContext(Dispatchers.IO) {
            runCatching {
                val req = Request.Builder().url(url).get().build()
                logoHttp.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@runCatching null
                    val bytes = resp.body?.bytes() ?: return@runCatching null
                    BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                }
            }.getOrNull()
        }
        if (remoteBmp == null) loadFailed = true
    }

    val bmp = remoteBmp
    if (!url.isBlank() && bmp != null && !loadFailed) {
        Image(
            bitmap = bmp.asImageBitmap(),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = modifier
                .size(resolvedBox)
                .clip(RoundedCornerShape(resolvedCorner)),
        )
        return
    }

    Box(
        modifier = modifier
            .size(resolvedBox)
            .background(Color.Black, RoundedCornerShape(resolvedCorner)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "S",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = resolvedLetter,
        )
    }
}
