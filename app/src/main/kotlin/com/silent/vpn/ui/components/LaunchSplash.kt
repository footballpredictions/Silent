package com.silent.vpn.ui.components



import androidx.compose.foundation.background

import androidx.compose.foundation.layout.Box

import androidx.compose.foundation.layout.fillMaxSize

import androidx.compose.runtime.Composable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.remember

import androidx.compose.ui.Alignment

import androidx.compose.ui.Modifier

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository



/** Адаптивный фон splash на телефоне и TV под светлую/тёмную тему. */

val LaunchSplashBg = Color.White
val LaunchSplashBgDark = Color(0xFF0B0F1A)



@Composable

fun LaunchSplash(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val savedMode = remember {
        runCatching {
            SilentPrefs.open(context)
                .getString(SilentRepository.PREF_APPEARANCE_MODE, null)
                ?.takeIf { it == "dark" || it == "light" }
        }.getOrNull()
    }
    val dark = when (savedMode) {
        "dark" -> true
        "light" -> false
        else -> isSystemInDarkTheme()
    }

    Box(

        modifier = modifier

            .fillMaxSize()

            .background(if (dark) LaunchSplashBgDark else LaunchSplashBg),

        contentAlignment = Alignment.Center,

    ) {

        BrandHeader(textColor = if (dark) Color(0xFFE5E7EB) else Color(0xFF111827))

    }

}

