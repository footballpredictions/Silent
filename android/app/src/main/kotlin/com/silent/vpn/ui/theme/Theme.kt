package com.silent.vpn.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData

fun ThemeData.toColorScheme(dark: Boolean): ColorScheme {
    val bg = parseColor(background_color, if (dark) Color.Black else Color.White)
    val fg = parseColor(text_color, if (dark) Color.White else Color.Black)
    val accent = parseColor(accent_color, Color(0xFF1A1A1A))
    val primary = parseColor(primary_color, Color.Black)
    return if (dark) {
        darkColorScheme(primary = primary, background = bg, surface = bg, onBackground = fg, onSurface = fg)
    } else {
        lightColorScheme(primary = primary, background = bg, surface = bg, onBackground = fg, onSurface = fg)
    }
}

fun parseColor(hex: String, fallback: Color): Color = try {
    Color(android.graphics.Color.parseColor(hex))
} catch (_: Exception) { fallback }

@Composable
fun SilentTheme(
    themeData: ThemeData? = null,
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = themeData?.toColorScheme(darkTheme)
        ?: if (darkTheme) darkColorScheme(primary = Color.White, background = Color.Black)
        else lightColorScheme(primary = Color.Black, background = Color.White)

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography(),
        content = content,
    )
}
