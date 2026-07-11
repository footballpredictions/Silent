package com.silent.vpn.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.util.rememberIsTv

/** Логотип + подпись — как на экране входа ([LoginScreen]). */
@Composable
fun BrandHeader(
    modifier: Modifier = Modifier,
    textColor: Color = Color.White,
) {
    val isTv = rememberIsTv()
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        SilentLogo()
        Spacer(modifier = Modifier.height(if (isTv) 16.dp else 12.dp))
        Text(
            text = "SILENT VPN",
            color = textColor,
            fontWeight = FontWeight.Bold,
            fontSize = if (isTv) 22.sp else 16.sp,
            letterSpacing = if (isTv) 4.sp else 3.sp,
        )
    }
}
