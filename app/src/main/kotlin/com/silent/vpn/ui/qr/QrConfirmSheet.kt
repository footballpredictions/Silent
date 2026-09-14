package com.silent.vpn.ui.qr

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.tv.TvPrimaryButton
import com.silent.vpn.ui.tv.TvTextButton

@Composable
fun QrConfirmSheet(
    visible: Boolean,
    theme: ThemeData?,
    fg: Color,
    hint: Color,
    red: Color,
    bg: Color,
    primaryBtnBg: Color,
    primaryBtnFg: Color,
    busy: Boolean,
    error: String?,
    loggedIn: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (!visible) return
    val title = theme?.login_qr_title?.takeIf { it.isNotBlank() } ?: "Вход по QR"
    val confirm = theme?.login_qr_confirm_label?.takeIf { it.isNotBlank() } ?: "Подтвердить вход на ТВ"
    val body = theme?.login_qr_confirm_hint?.takeIf { it.isNotBlank() }
        ?: "Телевизор войдёт в ваш аккаунт"
    Dialog(onDismissRequest = { if (!busy) onDismiss() }) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(bg, RoundedCornerShape(16.dp))
                .padding(22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(title, color = fg, fontWeight = FontWeight.SemiBold, fontSize = 16.sp)
            Spacer(Modifier.height(10.dp))
            Text(
                if (loggedIn) body else "Сначала войдите на этом телефоне, затем снова отсканируйте QR с ТВ",
                color = hint,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
            )
            if (!error.isNullOrBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(error, color = red, fontSize = 12.sp, textAlign = TextAlign.Center)
            }
            Spacer(Modifier.height(18.dp))
            if (busy) {
                CircularProgressIndicator(color = fg, strokeWidth = 2.dp, modifier = Modifier.padding(8.dp))
            } else if (loggedIn) {
                TvPrimaryButton(
                    onClick = onConfirm,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text(confirm, fontWeight = FontWeight.SemiBold, color = primaryBtnFg)
                }
                Spacer(Modifier.height(8.dp))
            }
            TvTextButton(onClick = onDismiss, enabled = !busy) {
                Text("Отмена", color = hint)
            }
        }
    }
}
