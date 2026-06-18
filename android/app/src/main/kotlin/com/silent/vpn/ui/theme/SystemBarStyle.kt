package com.silent.vpn.ui.theme

import android.app.Activity
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * Edge-to-edge: фон рисуется под status bar, иконки системы должны контрастировать с [backgroundColor].
 * light background → isAppearanceLightStatusBars=true (тёмные часы/батарея).
 */
@Composable
fun ApplySystemBarAppearance(backgroundColor: Color) {
    val view = LocalView.current
    val lifecycleOwner = LocalLifecycleOwner.current
    if (view.isInEditMode) return

    fun apply() {
        val window = (view.context as Activity).window
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.statusBarColor = android.graphics.Color.TRANSPARENT
        window.navigationBarColor = android.graphics.Color.TRANSPARENT
        val controller = WindowCompat.getInsetsController(window, view)
        val lightBackground = !isDarkBackground(backgroundColor)
        controller.isAppearanceLightStatusBars = lightBackground
        controller.isAppearanceLightNavigationBars = lightBackground
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
