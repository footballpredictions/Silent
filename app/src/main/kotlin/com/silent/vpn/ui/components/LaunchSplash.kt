package com.silent.vpn.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.ui.theme.parseColor
import kotlinx.coroutines.delay

/** Адаптивный фон splash на телефоне и TV под светлую/тёмную тему. */
val LaunchSplashBg = Color.White
val LaunchSplashBgDark = Color(0xFF0B0B0F)

@Composable
fun LaunchSplash(
    modifier: Modifier = Modifier,
    progress: Float = 0f,
    showProgress: Boolean = false,
) {
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
    val cachedTheme = remember {
        runCatching {
            val json = SilentPrefs.open(context).getString(SilentRepository.PREF_CACHED_THEME, null)
            if (json.isNullOrBlank()) null
            else com.google.gson.Gson().fromJson(json, com.silent.vpn.data.ThemeData::class.java)
        }.getOrNull()
    }
    val accentHex = if (dark) {
        cachedTheme?.dark_accent_color?.takeIf { it.isNotBlank() }
            ?: cachedTheme?.accent_color
    } else {
        cachedTheme?.accent_color
    }
    val accent = parseColor(
        accentHex.orEmpty(),
        if (dark) Color(0xFFE5E7EB) else Color(0xFF111827),
    )
    val track = if (dark) Color(0xFF27272A) else Color(0xFFE5E7EB)
    val animated = remember { Animatable(0f) }

    LaunchedEffect(progress, showProgress) {
        if (!showProgress) {
            animated.snapTo(0f)
            return@LaunchedEffect
        }
        val target = progress.coerceIn(0f, 1f)
        // Полоса не откатывается назад; догоняет реальное завершение bootstrap.
        if (target >= animated.value) {
            animated.animateTo(
                targetValue = target,
                animationSpec = tween(
                    durationMillis = if (target >= 0.99f) 220 else 420,
                    easing = FastOutSlowInEasing,
                ),
            )
        }
        // Лёгкий «пульс», пока ждём сеть — не уезжает дальше 0.92 без реальных данных.
        while (showProgress && animated.value < 0.92f && progress < 0.95f) {
            val creep = (animated.value + 0.012f).coerceAtMost(0.88f.coerceAtLeast(progress))
            if (creep > animated.value) {
                animated.animateTo(creep, tween(700, easing = FastOutSlowInEasing))
            }
            delay(120)
        }
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .background(if (dark) LaunchSplashBgDark else LaunchSplashBg),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            BrandHeader(textColor = if (dark) Color(0xFFE5E7EB) else Color(0xFF111827))
            if (showProgress) {
                Spacer(modifier = Modifier.height(28.dp))
                Box(
                    modifier = Modifier
                        .widthIn(max = 220.dp)
                        .fillMaxWidth(0.55f)
                        .height(3.dp)
                        .clip(RoundedCornerShape(99.dp))
                        .background(track),
                ) {
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(animated.value.coerceIn(0.04f, 1f))
                            .height(3.dp)
                            .clip(RoundedCornerShape(99.dp))
                            .background(accent),
                    )
                }
            }
        }
    }
}
