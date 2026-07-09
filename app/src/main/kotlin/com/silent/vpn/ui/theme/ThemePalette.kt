package com.silent.vpn.ui.theme

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Shadow
import com.silent.vpn.data.ThemeData

enum class AppearanceMode { LIGHT, DARK }

data class ThemePalette(
    val bg: Color,
    val fg: Color,
    val muted: Color,
    val dark: Boolean,
    val primary: Color,
    val accent: Color,
    val toggleOn: Color,
    val toggleOff: Color,
    val updateBarBg: Color,
    val updateBarFg: Color,
    val updateBarProgress: Color,
    val linkColor: Color,
    val border: Color,
    val borderStrong: Color,
    val surface: Color,
    val fieldBg: Color,
    val fieldText: Color,
    val fieldPlaceholder: Color,
    val label: Color,
    val hint: Color,
    val tabBg: Color,
    val divider: Color,
    val headerBg: Color,
    val headerFg: Color,
    val primaryBtnBg: Color,
    val primaryBtnFg: Color,
    val green: Color,
    val red: Color,
    val purple: Color,
)

private fun invertColor(c: Color): Color =
    Color(1f - c.red, 1f - c.green, 1f - c.blue, c.alpha)

private fun pick(darkHex: String?, light: Color, fallback: Color, wantDark: Boolean): Color {
    if (!wantDark) return light
    val d = darkHex?.trim().orEmpty()
    if (d.isNotEmpty()) return parseColor(d, fallback)
    return fallback
}

fun ThemeData?.resolveThemePalette(mode: AppearanceMode): ThemePalette {
    val wantDark = mode == AppearanceMode.DARK
    val lightBg = parseColor(this?.background_color ?: "#FFFFFF", Color.White)
    val lightFg = parseColor(this?.text_color ?: "#000000", Color.Black)
    val lightPrimary = parseColor(this?.primary_color ?: "#000000", lightFg)
    val lightAccent = parseColor(this?.accent_color ?: "#1A1A1A", Color(0xFF1A1A1A))
    val lightToggleOn = parseColor(this?.toggle_on_color ?: "#000000", Color.Black)
    val lightToggleOff = parseColor(this?.toggle_off_color ?: "#CCCCCC", Color(0xFFCCCCCC))
    val lightUpdateBg = parseColor(this?.update_bar_background_color ?: "#2563EB", Color(0xFF2563EB))
    val lightUpdateFg = parseColor(this?.update_bar_text_color ?: "#FFFFFF", Color.White)
    val lightUpdateProgress = parseColor(this?.update_bar_progress_color ?: "#1D4ED8", Color(0xFF1D4ED8))
    val lightLink = parseColor(this?.login_link_color ?: "#4680C2", Color(0xFF4680C2))

    val bg = pick(this?.dark_background_color, lightBg, Color(0xFF0B0B0F), wantDark)
    val fg = pick(this?.dark_text_color, lightFg, Color(0xFFF5F5F7), wantDark)
    val primary = pick(this?.dark_primary_color, lightPrimary, invertColor(lightPrimary), wantDark)
    val accent = pick(this?.dark_accent_color, lightAccent, invertColor(lightAccent), wantDark)
    val toggleOn = pick(this?.dark_toggle_on_color, lightToggleOn, Color.White, wantDark)
    val toggleOff = pick(this?.dark_toggle_off_color, lightToggleOff, Color(0xFF3F3F46), wantDark)
    val updateBarBg = pick(this?.dark_update_bar_background_color, lightUpdateBg, lightUpdateBg, wantDark)
    val updateBarFg = pick(this?.dark_update_bar_text_color, lightUpdateFg, lightUpdateFg, wantDark)
    val updateBarProgress = pick(this?.dark_update_bar_progress_color, lightUpdateProgress, lightUpdateProgress, wantDark)
    val linkColor = pick(this?.dark_login_link_color, lightLink, Color(0xFF7DD3FC), wantDark)

    val dark = isDarkBackground(bg)
    return ThemePalette(
        bg = bg,
        fg = fg,
        muted = fg.copy(alpha = if (dark) 0.7f else 0.6f),
        dark = dark,
        primary = primary,
        accent = accent,
        toggleOn = toggleOn,
        toggleOff = toggleOff,
        updateBarBg = updateBarBg,
        updateBarFg = updateBarFg,
        updateBarProgress = updateBarProgress,
        linkColor = linkColor,
        border = if (dark) Color(0xFF2A2A32) else Color(0xFFF3F4F6),
        borderStrong = if (dark) Color(0xFF3F3F46) else Color(0xFFE5E7EB),
        surface = if (dark) Color(0xFF14141A) else Color(0xFFF3F4F6),
        fieldBg = if (dark) Color(0xFF16161C) else Color(0xFFF3F4F6),
        fieldText = fg,
        fieldPlaceholder = if (dark) Color(0xFF9CA3AF) else Color(0xFF6B7280),
        label = if (dark) Color(0xFFD1D5DB) else Color(0xFF374151),
        hint = if (dark) Color(0xFF9CA3AF) else Color(0xFF6B7280),
        tabBg = if (dark) Color(0xFF1F1F26) else Color(0xFFF3F4F6),
        divider = if (dark) Color(0xFF2A2A32) else Color(0xFFE5E7EB),
        headerBg = if (dark) Color.Black else bg,
        headerFg = if (dark) Color(0xFF9CA3AF) else fg.copy(alpha = 0.6f),
        primaryBtnBg = if (dark) Color.White else fg,
        primaryBtnFg = if (dark) Color.Black else bg,
        green = if (dark) Color(0xFF4ADE80) else Color(0xFF16A34A),
        red = Color(0xFFEF4444),
        purple = if (dark) Color(0xFFC084FC) else Color(0xFF9333EA),
    )
}

fun needsNeonGlow(color: Color, darkSurface: Boolean): Boolean {
    if (!darkSurface) return false
    val lum = 0.299f * color.red + 0.587f * color.green + 0.114f * color.blue
    return lum > 0.18f && lum < 0.72f
}

fun neonShadow(color: Color): Shadow = Shadow(
    color = color.copy(alpha = 0.65f),
    offset = Offset.Zero,
    blurRadius = 12f,
)
