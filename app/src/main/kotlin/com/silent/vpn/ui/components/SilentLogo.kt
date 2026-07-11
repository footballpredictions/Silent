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
import com.silent.vpn.util.rememberIsTv

/** Brand mark: black rounded square + white S. На TV крупнее, чтобы не мылить. */
@Composable
fun SilentLogo(
    modifier: Modifier = Modifier,
    boxSize: Dp? = null,
    cornerRadius: Dp? = null,
    letterSize: TextUnit? = null,
) {
    val isTv = rememberIsTv()
    val resolvedBox = boxSize ?: if (isTv) 88.dp else 56.dp
    val resolvedCorner = cornerRadius ?: if (isTv) 24.dp else 16.dp
    val resolvedLetter = letterSize ?: if (isTv) 36.sp else 22.sp
    Box(
        modifier = modifier
            .size(resolvedBox)
            .background(Color.Black, RoundedCornerShape(resolvedCorner)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = "S",
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = resolvedLetter,
        )
    }
}
