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

/** Логотип + подпись — как на экране входа ([LoginScreen]). */
@Composable
fun BrandHeader(
    modifier: Modifier = Modifier,
    textColor: Color = Color.White,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        SilentLogo()
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "SILENT VPN",
            color = textColor,
            fontWeight = FontWeight.Bold,
            fontSize = 16.sp,
            letterSpacing = 3.sp,
        )
    }
}
