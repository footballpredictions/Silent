package com.silent.vpn.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathOperation
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.silent.vpn.ui.theme.AppearanceMode
import kotlin.math.cos
import kotlin.math.sin

/**
 * Telegram-style sun ↔ moon icon.
 * Crescent = disc − offset circle (Path.op DIFFERENCE), not two halves.
 */
@Composable
fun ThemeModeToggle(
    mode: AppearanceMode,
    onToggle: () -> Unit,
    color: Color,
    modifier: Modifier = Modifier,
) {
    val dark = mode == AppearanceMode.DARK
    val progress = remember { Animatable(if (dark) 1f else 0f) }
    LaunchedEffect(dark) {
        progress.animateTo(
            targetValue = if (dark) 1f else 0f,
            animationSpec = tween(durationMillis = 520, easing = FastOutSlowInEasing),
        )
    }

    Box(
        modifier = modifier
            .size(28.dp)
            .clickable(
                interactionSource = remember { MutableInteractionSource() },
                indication = null,
                role = Role.Switch,
                onClick = onToggle,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(22.dp)) {
            val t = progress.value
            val cx = size.width / 2f
            val cy = size.height / 2f
            val discR = size.minDimension * 0.22f
            val ink = color

            val rayAlpha = (1f - t * 1.1f).coerceIn(0f, 1f)
            if (rayAlpha > 0.02f) {
                val rayLen = size.minDimension * 0.44f
                withTransform({
                    rotate(degrees = 90f * t, pivot = Offset(cx, cy))
                    scale(scaleX = 1f - 0.55f * t, scaleY = 1f - 0.55f * t, pivot = Offset(cx, cy))
                }) {
                    for (i in 0 until 8) {
                        val ang = Math.toRadians(i * 45.0)
                        val inner = discR + size.minDimension * 0.05f
                        drawLine(
                            color = ink.copy(alpha = rayAlpha),
                            start = Offset(cx + cos(ang).toFloat() * inner, cy + sin(ang).toFloat() * inner),
                            end = Offset(cx + cos(ang).toFloat() * rayLen, cy + sin(ang).toFloat() * rayLen),
                            strokeWidth = size.minDimension * 0.07f,
                        )
                    }
                }
            }

            val discScale = 1f + 0.08f * t
            val discRot = -28f * t
            withTransform({
                rotate(degrees = discRot, pivot = Offset(cx, cy))
                scale(scaleX = discScale, scaleY = discScale, pivot = Offset(cx, cy))
            }) {
                if (t < 0.02f) {
                    drawCircle(color = ink, radius = discR, center = Offset(cx, cy))
                } else {
                    // Classic crescent: disc − offset circle
                    val cutCx = cx + discR * 0.58f
                    val cutCy = cy - discR * 0.32f
                    val cutR = discR * (0.82f + 0.08f * t)
                    val disc = Path().apply {
                        addOval(Rect(cx - discR, cy - discR, cx + discR, cy + discR))
                    }
                    val cut = Path().apply {
                        addOval(Rect(cutCx - cutR, cutCy - cutR, cutCx + cutR, cutCy + cutR))
                    }
                    val crescent = Path().apply {
                        op(disc, cut, PathOperation.Difference)
                    }
                    drawPath(crescent, color = ink)
                }
            }
        }
    }
}
