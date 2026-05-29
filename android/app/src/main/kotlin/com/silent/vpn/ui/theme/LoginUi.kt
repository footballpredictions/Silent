package com.silent.vpn.ui.theme

import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.TextFieldColors
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.silent.vpn.data.ThemeData

/** Палитра экрана входа — как [themeToUi] в PC `clientTheme.ts`. */
data class LoginUi(
    val bg: Color,
    val fg: Color,
    val fieldBg: Color,
    val fieldText: Color,
    val fieldPlaceholder: Color,
    val label: Color,
    val hint: Color,
    val border: Color,
    val borderFocused: Color,
    val tabBg: Color,
    val divider: Color,
    val headerBg: Color,
    val headerFg: Color,
    val primaryBtnBg: Color,
    val primaryBtnFg: Color,
    val green: Color = Color(0xFF16A34A),
    val red: Color = Color(0xFFEF4444),
)

private fun isDarkBackground(bg: Color): Boolean {
    val lum = 0.299f * bg.red + 0.587f * bg.green + 0.114f * bg.blue
    return lum < 0.45f
}

fun ThemeData?.toLoginUi(): LoginUi {
    val bg = parseColor(this?.background_color ?: "#FFFFFF", Color.White)
    val fg = parseColor(this?.text_color ?: "#000000", Color.Black)
    val dark = isDarkBackground(bg)
    return LoginUi(
        bg = bg,
        fg = fg,
        fieldBg = if (dark) Color(0xFF161616) else Color(0xFFF3F4F6),
        fieldText = fg,
        fieldPlaceholder = if (dark) Color(0xFF9CA3AF) else Color(0xFF6B7280),
        label = if (dark) Color(0xFFD1D5DB) else Color(0xFF374151),
        hint = if (dark) Color(0xFF9CA3AF) else Color(0xFF6B7280),
        border = if (dark) Color(0xFF374151) else Color(0xFFE5E7EB),
        borderFocused = if (dark) Color(0xFFE5E7EB) else Color(0xFF111827),
        tabBg = if (dark) Color(0xFF1F1F1F) else Color(0xFFF3F4F6),
        divider = if (dark) Color(0xFF2A2A2A) else Color(0xFFE5E7EB),
        headerBg = if (dark) Color.Black else bg,
        headerFg = if (dark) Color(0xFF9CA3AF) else fg.copy(alpha = 0.6f),
        primaryBtnBg = if (dark) Color.White else fg,
        primaryBtnFg = if (dark) Color.Black else bg,
    )
}

@Composable
fun loginTextFieldColors(ui: LoginUi): TextFieldColors = OutlinedTextFieldDefaults.colors(
    focusedTextColor = ui.fieldText,
    unfocusedTextColor = ui.fieldText,
    disabledTextColor = ui.fieldText.copy(alpha = 0.5f),
    cursorColor = ui.fieldText,
    focusedContainerColor = ui.fieldBg,
    unfocusedContainerColor = ui.fieldBg,
    disabledContainerColor = ui.fieldBg,
    focusedBorderColor = ui.borderFocused,
    unfocusedBorderColor = ui.border,
    focusedPlaceholderColor = ui.fieldPlaceholder,
    unfocusedPlaceholderColor = ui.fieldPlaceholder,
)
