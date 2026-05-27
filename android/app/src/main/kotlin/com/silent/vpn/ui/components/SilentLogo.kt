package com.silent.vpn.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Brand mark: black rounded square + white S (56dp / 16dp / 22sp on login screen). */
@Composable
fun SilentLogo(
    modifier: Modifier = Modifier,
    boxSize: Dp = 56.dp,
    cornerRadius: Dp = 16.dp,
    letterSize: TextUnit = 22.sp,
) {
    Box(
        modifier = modifier
            .size(boxSize)
            .background(Color.Black, RoundedCornerShape(cornerRadius)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "S",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = letterSize,
        )
    }
}
