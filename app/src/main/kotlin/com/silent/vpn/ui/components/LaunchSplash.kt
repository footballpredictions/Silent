package com.silent.vpn.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color

/** Белый фон splash на телефоне и TV (логотип с чёрным квадратом). */
val LaunchSplashBg = Color.White

@Composable
fun LaunchSplash(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(LaunchSplashBg),
        contentAlignment = Alignment.Center,
    ) {
        BrandHeader(textColor = Color(0xFF111827))
    }
}
