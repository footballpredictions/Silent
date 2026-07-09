package com.silent.vpn.ui.theme

import android.app.Activity
import androidx.compose.runtime.Composable
import com.silent.vpn.util.rememberIsTv
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/** Серые полосы status/nav bar в тёмной теме — отделяют контент приложения от системных панелей. */
val DarkSystemBarStrip = Color(0xFF2A2A32)

private fun Color.toArgbInt(): Int = android.graphics.Color.argb(
    (alpha * 255).toInt().coerceIn(0, 255),
    (red * 255).toInt().coerceIn(0, 255),
    (green * 255).toInt().coerceIn(0, 255),
    (blue * 255).toInt().coerceIn(0, 255),
)

/**
 * Edge-to-edge: фон рисуется под status bar, иконки системы должны контрастировать с [backgroundColor].
 * light background → isAppearanceLightStatusBars=true (тёмные часы/батарея).
 * dark → status/nav = серые полоски ([DarkSystemBarStrip]), контент остаётся [backgroundColor].
 *
 * Важно: экраны должны рисовать [DarkSystemBarStrip] под insets и [backgroundColor] только
 * в safeDrawing-области, иначе Compose-фон перекроет цвет системных панелей.
 */
@Composable
fun ApplySystemBarAppearance(backgroundColor: Color) {
    val view = LocalView.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val isTv = rememberIsTv()
    if (view.isInEditMode) return

    fun apply() {
        val window = (view.context as Activity).window
        if (isTv) {
            WindowCompat.setDecorFitsSystemWindows(window, true)
            window.statusBarColor = android.graphics.Color.TRANSPARENT
            window.navigationBarColor = android.graphics.Color.TRANSPARENT
            return
        }
        WindowCompat.setDecorFitsSystemWindows(window, false)
        val dark = isDarkBackground(backgroundColor)
        // В dark — серые полосы; в light — тот же цвет, что фон (без «шва»)
        val barArgb = (if (dark) DarkSystemBarStrip else backgroundColor).toArgbInt()
        // Непрозрачный цвет — иначе на части OEM nav bar остаётся белой полосой
        window.statusBarColor = barArgb
        window.navigationBarColor = barArgb
        val controller = WindowCompat.getInsetsController(window, view)
        controller.isAppearanceLightStatusBars = !dark
        controller.isAppearanceLightNavigationBars = !dark
    }

    SideEffect { apply() }

    DisposableEffect(lifecycleOwner, backgroundColor) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) apply()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
}
