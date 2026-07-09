package com.silent.vpn.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import com.silent.vpn.data.ThemeData

fun ThemeData.toColorScheme(dark: Boolean): ColorScheme {
    val mode = if (dark) AppearanceMode.DARK else AppearanceMode.LIGHT
    val p = resolveThemePalette(mode)
    return if (dark) {
        darkColorScheme(
            primary = p.primary,
            background = p.bg,
            surface = p.bg,
            onBackground = p.fg,
            onSurface = p.fg,
            onPrimary = p.primaryBtnFg,
        )
    } else {
        lightColorScheme(
            primary = p.primary,
            background = p.bg,
            surface = p.bg,
            onBackground = p.fg,
            onSurface = p.fg,
            onPrimary = p.primaryBtnFg,
        )
    }
}

fun parseColor(hex: String, fallback: Color): Color = try {
    Color(android.graphics.Color.parseColor(hex))
} catch (_: Exception) {
    fallback
}

/** Светлый фон → тёмные иконки status bar; тёмный фон → светлые иконки. */
fun isDarkBackground(color: Color): Boolean {
    val lum = 0.299f * color.red + 0.587f * color.green + 0.114f * color.blue
    return lum < 0.45f
}

@Composable
fun SilentTheme(
    themeData: ThemeData? = null,
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = remember(themeData, darkTheme) {
        themeData?.toColorScheme(darkTheme)
            ?: if (darkTheme) {
                darkColorScheme(primary = Color.White, background = Color(0xFF0B0B0F), surface = Color(0xFF0B0B0F))
            } else {
                lightColorScheme(primary = Color.Black, background = Color.White, surface = Color.White)
            }
    }

    // Важно: фон из resolved dark palette, иначе nav bar остаётся «светлой» при белом theme.background_color
    ApplySystemBarAppearance(colorScheme.background)

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        content = content,
    )
}
