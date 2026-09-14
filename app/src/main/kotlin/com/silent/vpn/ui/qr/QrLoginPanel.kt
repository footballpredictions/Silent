package com.silent.vpn.ui.qr

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.tv.TvPrimaryButton
import com.silent.vpn.util.rememberIsTv

@Composable
fun QrLoginPanel(
    theme: ThemeData?,
    fg: Color,
    hint: Color,
    green: Color,
    red: Color,
    primaryBtnBg: Color,
    primaryBtnFg: Color,
    payload: String,
    waiting: Boolean,
    expired: Boolean,
    loading: Boolean,
    error: String?,
    statusText: String,
    onRefresh: () -> Unit,
) {
    val isTv = rememberIsTv()
    val tabLabel = theme?.login_qr_tab_label?.takeIf { it.isNotBlank() } ?: "QR"
    val title = theme?.login_qr_title?.takeIf { it.isNotBlank() } ?: "Вход по QR"
    val showHint = theme?.login_qr_show_hint?.takeIf { it.isNotBlank() }
        ?: "Отсканируйте код любым сканером на телефоне — откроется Silent VPN"
    val waitingText = theme?.login_qr_waiting?.takeIf { it.isNotBlank() } ?: "Ожидание подтверждения…"
    val expiredText = theme?.login_qr_expired?.takeIf { it.isNotBlank() } ?: "Код истёк — обновите"
    val qrSize = if (isTv) 280.dp else 200.dp
    val density = LocalDensity.current
    val bitmap = remember(payload, qrSize) {
        if (payload.isBlank()) null
        else qrCodeBitmap(payload, with(density) { qrSize.roundToPx() })
    }

    Text(title, color = fg, fontWeight = FontWeight.SemiBold, fontSize = if (isTv) 18.sp else 14.sp)
    Spacer(Modifier.height(8.dp))
    Text(showHint, color = hint, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    Spacer(Modifier.height(12.dp))
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(qrSize + 24.dp),
        contentAlignment = Alignment.Center,
    ) {
        when {
            loading && payload.isBlank() -> CircularProgressIndicator(color = fg, strokeWidth = 2.dp, modifier = Modifier.size(28.dp))
            bitmap != null -> Image(
                bitmap = bitmap.asImageBitmap(),
                contentDescription = tabLabel,
                modifier = Modifier
                    .size(qrSize)
                    .clip(RoundedCornerShape(12.dp))
                    .background(Color.White)
                    .padding(8.dp),
            )
        }
    }
    val footer = when {
        expired -> expiredText
        statusText.isNotBlank() -> statusText
        waiting -> waitingText
        else -> ""
    }
    if (footer.isNotBlank()) {
        Text(
            footer,
            color = if (expired) red else green,
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        )
    }
    Spacer(Modifier.height(12.dp))
    TvPrimaryButton(
        onClick = onRefresh,
        enabled = !loading,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
    ) {
        Text(if (expired) expiredText else "Обновить код", fontWeight = FontWeight.SemiBold)
    }
    if (!error.isNullOrBlank()) {
        Text(error, color = red, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
    }
}
