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
    val linkColor: Color = Color(0xFF4680C2),
    val dark: Boolean = false,
)

fun ThemeData?.toLoginUi(mode: AppearanceMode = AppearanceMode.LIGHT): LoginUi {
    val p = resolveThemePalette(mode)
    return LoginUi(
        bg = p.bg,
        fg = p.fg,
        fieldBg = p.fieldBg,
        fieldText = p.fieldText,
        fieldPlaceholder = p.fieldPlaceholder,
        label = p.label,
        hint = p.hint,
        border = p.borderStrong,
        borderFocused = if (p.dark) Color(0xFFE5E7EB) else Color(0xFF111827),
        tabBg = p.tabBg,
        divider = p.divider,
        headerBg = p.headerBg,
        headerFg = p.headerFg,
        primaryBtnBg = p.primaryBtnBg,
        primaryBtnFg = p.primaryBtnFg,
        green = p.green,
        red = p.red,
        linkColor = p.linkColor,
        dark = p.dark,
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

/** Цвета полей ввода для меню (бонусы, исключения, переименование) — как на логине. */
@Composable
fun themeTextFieldColors(palette: ThemePalette): TextFieldColors = OutlinedTextFieldDefaults.colors(
    focusedTextColor = palette.fieldText,
    unfocusedTextColor = palette.fieldText,
    disabledTextColor = palette.fieldText.copy(alpha = 0.5f),
    cursorColor = palette.fieldText,
    focusedContainerColor = palette.fieldBg,
    unfocusedContainerColor = palette.fieldBg,
    disabledContainerColor = palette.fieldBg,
    focusedBorderColor = if (palette.dark) Color(0xFFE5E7EB) else Color(0xFF111827),
    unfocusedBorderColor = palette.borderStrong,
    focusedPlaceholderColor = palette.fieldPlaceholder,
    unfocusedPlaceholderColor = palette.fieldPlaceholder,
)
