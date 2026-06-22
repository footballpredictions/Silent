package com.silent.vpn.ui.components

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

@Composable
fun LoginExpiredPanel(
    fg: Color,
    hint: Color,
    accentColor: Color,
    primaryBtnBg: Color,
    primaryBtnFg: Color,
    onCloseApp: () -> Unit,
    modifier: Modifier = Modifier,
    title: String = "Время вышло",
    body: String = "Временный интернет на 2 минуты закончился.\nЗакройте приложение и откройте снова.",
    closeLabel: String = "Закрыть приложение",
) {
    var revealed by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        revealed = false
        delay(40)
        revealed = true
    }

    val cardScale by animateFloatAsState(
        targetValue = if (revealed) 1f else 0.97f,
        animationSpec = tween(240, easing = FastOutSlowInEasing),
        label = "expiredCardScale",
    )
    val cardAlpha by animateFloatAsState(
        targetValue = if (revealed) 1f else 0f,
        animationSpec = tween(220, easing = FastOutSlowInEasing),
        label = "expiredCardAlpha",
    )
    val bodyAlpha by animateFloatAsState(
        targetValue = if (revealed) 1f else 0f,
        animationSpec = tween(200, delayMillis = 90, easing = FastOutSlowInEasing),
        label = "expiredBodyAlpha",
    )
    val buttonAlpha by animateFloatAsState(
        targetValue = if (revealed) 1f else 0f,
        animationSpec = tween(200, delayMillis = 160, easing = FastOutSlowInEasing),
        label = "expiredButtonAlpha",
    )

    Column(
        modifier = modifier
            .fillMaxWidth()
            .scale(cardScale)
            .alpha(cardAlpha),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .border(1.dp, accentColor.copy(alpha = 0.18f), RoundedCornerShape(16.dp))
                .background(accentColor.copy(alpha = 0.05f), RoundedCornerShape(16.dp))
                .padding(horizontal = 20.dp, vertical = 22.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .background(accentColor.copy(alpha = 0.1f), CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.Schedule,
                    contentDescription = null,
                    tint = accentColor,
                    modifier = Modifier.size(22.dp),
                )
            }
            Spacer(modifier = Modifier.height(14.dp))
            Text(
                text = title,
                color = fg,
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                textAlign = TextAlign.Center,
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = body,
                color = hint,
                fontSize = 12.sp,
                lineHeight = 17.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.alpha(bodyAlpha),
            )
            Spacer(modifier = Modifier.height(18.dp))
            Button(
                onClick = onCloseApp,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp)
                    .alpha(buttonAlpha),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = primaryBtnBg,
                    contentColor = primaryBtnFg,
                ),
            ) {
                Text(closeLabel, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
            }
        }
    }
}
