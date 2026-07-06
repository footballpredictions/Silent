package com.silent.vpn.ui.tv

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.clickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.silent.vpn.util.rememberIsTv
import kotlinx.coroutines.launch

object TvFocusColors {
    val ring = Color(0xFF2563EB)
    val fill = Color(0xFF2563EB).copy(alpha = 0.10f)
}

private fun Modifier.tvDpadCore(
    enabled: Boolean,
    interactionSource: MutableInteractionSource,
    onClick: () -> Unit,
): Modifier = this
    .focusable(enabled = enabled, interactionSource = interactionSource)
    .onPreviewKeyEvent { event ->
        if (!enabled) return@onPreviewKeyEvent false
        if (event.type != KeyEventType.KeyUp) return@onPreviewKeyEvent false
        when (event.key) {
            Key.DirectionCenter, Key.Enter, Key.NumPadEnter, Key.Spacebar -> {
                onClick()
                true
            }
            else -> false
        }
    }
    .clickable(
        enabled = enabled,
        interactionSource = interactionSource,
        indication = null,
        onClick = onClick,
    )

@OptIn(ExperimentalFoundationApi::class)
private fun Modifier.tvFocusRingDraw(
    focused: Boolean,
    cornerRadius: Dp,
    pill: Boolean,
    ringOnly: Boolean,
): Modifier {
    if (!focused) return this
    return drawBehind {
        val stroke = 2.5.dp.toPx()
        val inset = stroke / 2f
        val w = size.width - stroke
        val h = size.height - stroke
        if (w <= 0f || h <= 0f) return@drawBehind
        val radius = when {
            pill -> h / 2f
            else -> cornerRadius.toPx().coerceAtMost(minOf(w, h) / 2f)
        }
        val topLeft = Offset(inset, inset)
        val rectSize = Size(w, h)
        val corners = CornerRadius(radius, radius)
        if (!ringOnly) {
            drawRoundRect(
                color = TvFocusColors.fill,
                topLeft = topLeft,
                size = rectSize,
                cornerRadius = corners,
            )
        }
        drawRoundRect(
            color = TvFocusColors.ring,
            topLeft = topLeft,
            size = rectSize,
            cornerRadius = corners,
            style = Stroke(width = stroke),
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
private fun Modifier.tvFocusRingDrawOnTop(
    focused: Boolean,
    cornerRadius: Dp,
    pill: Boolean,
    ringOnly: Boolean,
): Modifier {
    if (!focused) return this
    return drawWithContent {
        drawContent()
        val stroke = 2.5.dp.toPx()
        val inset = stroke / 2f
        val w = size.width - stroke
        val h = size.height - stroke
        if (w <= 0f || h <= 0f) return@drawWithContent
        val radius = when {
            pill -> h / 2f
            else -> cornerRadius.toPx().coerceAtMost(minOf(w, h) / 2f)
        }
        val topLeft = Offset(inset, inset)
        val rectSize = Size(w, h)
        val corners = CornerRadius(radius, radius)
        if (!ringOnly) {
            drawRoundRect(
                color = TvFocusColors.fill,
                topLeft = topLeft,
                size = rectSize,
                cornerRadius = corners,
            )
        }
        drawRoundRect(
            color = TvFocusColors.ring,
            topLeft = topLeft,
            size = rectSize,
            cornerRadius = corners,
            style = Stroke(width = stroke),
        )
    }
}

/** Не отдавать фокус вверх (верхний «Назад» в подменю). */
fun Modifier.tvConsumeFocusUp(): Modifier = onPreviewKeyEvent { event ->
    event.type == KeyEventType.KeyDown && event.key == Key.DirectionUp
}

/** D-pad + синее кольцо (без изменения размера — не дёргается). */
@OptIn(ExperimentalFoundationApi::class)
fun Modifier.tvClickable(
    enabled: Boolean = true,
    cornerRadius: Dp = 10.dp,
    pill: Boolean = false,
    ringOnly: Boolean = false,
    ringOnTop: Boolean = false,
    onClick: () -> Unit,
): Modifier = composed {
    if (!rememberIsTv()) {
        return@composed clickable(enabled = enabled, onClick = onClick)
    }
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val bringIntoViewRequester = remember { BringIntoViewRequester() }
    val scope = rememberCoroutineScope()
    val ringMod = if (ringOnTop) {
        Modifier.tvFocusRingDrawOnTop(focused, cornerRadius, pill, ringOnly)
    } else {
        Modifier.tvFocusRingDraw(focused, cornerRadius, pill, ringOnly)
    }

    this
        .bringIntoViewRequester(bringIntoViewRequester)
        .onFocusChanged { state ->
            if (state.isFocused) scope.launch { bringIntoViewRequester.bringIntoView() }
        }
        .then(ringMod)
        .tvDpadCore(enabled, interactionSource, onClick)
}

fun Modifier.tvMenuClickable(
    enabled: Boolean = true,
    cornerRadius: Dp = 10.dp,
    onClick: () -> Unit,
): Modifier = tvClickable(enabled = enabled, cornerRadius = cornerRadius, onClick = onClick)

@OptIn(ExperimentalFoundationApi::class)
fun Modifier.tvToggleClickable(
    enabled: Boolean = true,
    onClick: () -> Unit,
): Modifier = composed {
    if (!rememberIsTv()) {
        return@composed clickable(enabled = enabled, onClick = onClick)
    }
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val bringIntoViewRequester = remember { BringIntoViewRequester() }
    val scope = rememberCoroutineScope()

    this
        .bringIntoViewRequester(bringIntoViewRequester)
        .onFocusChanged { state ->
            if (state.isFocused) scope.launch { bringIntoViewRequester.bringIntoView() }
        }
        .tvFocusRingDrawOnTop(focused, cornerRadius = 30.dp, pill = true, ringOnly = true)
        .tvDpadCore(enabled, interactionSource, onClick)
}

/** Фокус для прокрутки списка на TV (без действия по OK). */
@OptIn(ExperimentalFoundationApi::class)
fun Modifier.tvListItemFocusable(): Modifier = composed {
    if (!rememberIsTv()) return@composed this
    val bringIntoViewRequester = remember { BringIntoViewRequester() }
    val scope = rememberCoroutineScope()
    this
        .bringIntoViewRequester(bringIntoViewRequester)
        .focusable()
        .onFocusChanged { state ->
            if (state.isFocused) scope.launch { bringIntoViewRequester.bringIntoView() }
        }
}

/** Слайдер: фокус + влево/вправо меняют значение, визуал как на телефоне. */
@OptIn(ExperimentalFoundationApi::class)
fun Modifier.tvSliderDpad(
    enabled: Boolean,
    value: Int,
    minValue: Int,
    maxValue: Int,
    step: Int,
    onValueChange: (Int) -> Unit,
): Modifier = composed {
    if (!rememberIsTv()) return@composed this
    val interactionSource = remember { MutableInteractionSource() }
    val focused by interactionSource.collectIsFocusedAsState()
    val bringIntoViewRequester = remember { BringIntoViewRequester() }
    val scope = rememberCoroutineScope()

    fun snap(raw: Int): Int {
        val stepped = (raw / step) * step
        return stepped.coerceIn(minValue, maxValue)
    }

    this
        .bringIntoViewRequester(bringIntoViewRequester)
        .onFocusChanged { state ->
            if (state.isFocused) scope.launch { bringIntoViewRequester.bringIntoView() }
        }
        .tvFocusRingDraw(focused, cornerRadius = 8.dp, pill = false, ringOnly = true)
        .focusable(enabled = enabled, interactionSource = interactionSource)
        .onPreviewKeyEvent { event ->
            if (!enabled) return@onPreviewKeyEvent false
            if (event.type != KeyEventType.KeyDown) return@onPreviewKeyEvent false
            when (event.key) {
                Key.DirectionLeft -> {
                    onValueChange(snap(value - step))
                    true
                }
                Key.DirectionRight -> {
                    onValueChange(snap(value + step))
                    true
                }
                else -> false
            }
        }
}

@Composable
fun Modifier.tvRequestFocusOnOpen(
    enabled: Boolean = true,
    requestKey: Any? = Unit,
): Modifier = composed {
    if (!rememberIsTv() || !enabled) return@composed this
    val requester = remember { FocusRequester() }
    LaunchedEffect(requestKey, enabled) {
        if (enabled) {
            kotlinx.coroutines.delay(100)
            requester.requestFocus()
        }
    }
    this.focusRequester(requester)
}

@Composable
fun tvScale(default: Float, tv: Float): Float {
    return if (rememberIsTv()) tv else default
}
