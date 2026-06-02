package com.silent.vpn.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData

/** Общие токены UI — синхронизированы с Tailwind/PC (index.css, MainScreen.tsx). */
object UiColors {
    val Gray100 = Color(0xFFF3F4F6)
    val Gray200 = Color(0xFFE5E7EB)
    val Gray300 = Color(0xFFD1D5DB)
    val Gray400 = Color(0xFF9CA3AF)
    val Red500 = Color(0xFFEF4444)
    val Green500 = Color(0xFF22C55E)
    val Green600 = Color(0xFF16A34A)
}

object UiDimens {
    val borderThin = 1.dp
    val menuWidth = 208.dp
    val titleBarHeight = 36.dp
    val menuNavPadding = 8.dp
    val menuItemPaddingH = 12.dp
    val menuItemPaddingV = 10.dp
    val pagePadding = 16.dp
}

object UiFont {
    val xs = 12.sp
    val sm = 14.sp
    val caption = 11.sp
    val titleTracking = 3.sp
}

fun displayAppName(theme: ThemeData?): String {
    val raw = theme?.app_name?.takeIf { it.isNotBlank() } ?: "Silent VPN"
    val name = if (raw.equals("Silent", ignoreCase = true)) "Silent VPN" else raw
    return name.uppercase()
}

fun mutedFg(fg: Color, alpha: Float = 0.4f): Color = fg.copy(alpha = alpha)
