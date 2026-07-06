package com.silent.vpn.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.silent.vpn.ui.tv.tvSliderDpad
import com.silent.vpn.util.rememberIsTv
import kotlin.math.roundToInt

/**
 * Ползунок как [input type=range] на PC/Electron: тонкая дорожка + круглый thumb.
 * На TV: фокус + ←/→ двигают шарик (тот же вид).
 */
@Composable
fun PcStyleRangeSlider(
    value: Int,
    onValueChange: (Int) -> Unit,
    minValue: Int,
    maxValue: Int,
    step: Int,
    enabled: Boolean,
    accent: Color,
    modifier: Modifier = Modifier,
) {
    val thumbSize = 18.dp
    val trackHeight = 4.dp
    val isTv = rememberIsTv()

    fun snap(raw: Float): Int {
        val stepped = (raw / step).roundToInt() * step
        return stepped.coerceIn(minValue, maxValue)
    }

    BoxWithConstraints(
        modifier = modifier
            .fillMaxWidth()
            .height(28.dp)
            .alpha(if (enabled) 1f else 0.45f)
            .then(
                if (isTv) {
                    Modifier.tvSliderDpad(
                        enabled = enabled,
                        value = value,
                        minValue = minValue,
                        maxValue = maxValue,
                        step = step,
                        onValueChange = onValueChange,
                    )
                } else {
                    Modifier
                },
            ),
    ) {
        val density = LocalDensity.current
        val widthPx = with(density) { maxWidth.toPx() }
        val thumbPx = with(density) { thumbSize.toPx() }
        val travel = (widthPx - thumbPx).coerceAtLeast(1f)
        val range = (maxValue - minValue).toFloat().coerceAtLeast(step.toFloat())
        val fraction = if (range > 0f) (value - minValue) / range else 0f
        val thumbX = fraction * travel
        val activeFraction = ((thumbX + thumbPx / 2f) / widthPx).coerceIn(0f, 1f)

        val accentColor = if (enabled) accent else accent.copy(alpha = 0.38f)

        fun updateFromX(x: Float) {
            val f = (x - thumbPx / 2f).coerceIn(0f, travel) / travel
            onValueChange(snap(minValue + f * range))
        }

        Box(
            Modifier
                .matchParentSize()
                .then(
                    if (!isTv) {
                        Modifier.pointerInput(enabled, minValue, maxValue, step, widthPx, thumbPx) {
                            if (!enabled) return@pointerInput
                            awaitEachGesture {
                                val down = awaitFirstDown(requireUnconsumed = false)
                                down.consume()
                                updateFromX(down.position.x)
                                val pointerId = down.id
                                while (true) {
                                    val event = awaitPointerEvent()
                                    val change = event.changes.firstOrNull { it.id == pointerId } ?: break
                                    if (!change.pressed) break
                                    updateFromX(change.position.x)
                                    change.consume()
                                }
                            }
                        }
                    } else {
                        Modifier
                    },
                ),
        ) {
            Box(
                Modifier
                    .align(Alignment.Center)
                    .fillMaxWidth()
                    .height(trackHeight)
                    .clip(RoundedCornerShape(2.dp))
                    .background(accent.copy(alpha = if (enabled) 0.12f else 0.08f)),
            )
            Box(
                Modifier
                    .align(Alignment.CenterStart)
                    .fillMaxWidth(activeFraction.coerceAtLeast(0.001f))
                    .height(trackHeight)
                    .clip(RoundedCornerShape(2.dp))
                    .background(accentColor),
            )
            Box(
                Modifier
                    .align(Alignment.CenterStart)
                    .offset { IntOffset(thumbX.roundToInt(), 0) }
                    .size(thumbSize)
                    .clip(CircleShape)
                    .background(accentColor),
            )
        }
    }
}
