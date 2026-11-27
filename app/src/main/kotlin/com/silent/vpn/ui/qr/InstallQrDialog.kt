package com.silent.vpn.ui.qr

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable

internal enum class MobileInstaller(val title: String) { Android("Android"), Ios("iOS") }

private const val TESTFLIGHT_APP = "https://apps.apple.com/app/testflight/id899247664"
private const val TESTFLIGHT_INVITATION = "https://testflight.apple.com/join/FVCNuq38"

@Composable
internal fun InstallQrDialog(
    platform: MobileInstaller,
    bg: Color,
    fg: Color,
    loadApk: suspend () -> String?,
    onOpenUrl: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var apk by remember(platform) { mutableStateOf<String?>(null) }
    var loading by remember(platform) { mutableStateOf(platform == MobileInstaller.Android) }
    var attempt by remember(platform) { mutableIntStateOf(0) }
    LaunchedEffect(platform, attempt) {
        if (platform == MobileInstaller.Android) {
            apk = loadApk()
            loading = false
        }
    }
    val height = LocalConfiguration.current.screenHeightDp.dp * 0.9f
    Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier.fillMaxWidth().heightIn(max = height)
                .background(bg, RoundedCornerShape(16.dp)).padding(18.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(platform.title, color = fg, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
            Column(
                modifier = Modifier.weight(1f, fill = false).fillMaxWidth().verticalScroll(rememberScrollState()),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                when {
                    platform == MobileInstaller.Ios -> {
                        InstallQr("TestFlight", TESTFLIGHT_APP, fg, onOpenUrl)
                        InstallQr("Silent VPN", TESTFLIGHT_INVITATION, fg, onOpenUrl)
                    }
                    loading -> CircularProgressIndicator(color = fg, modifier = Modifier.size(28.dp))
                    apk != null -> InstallQr("Silent VPN для Android", requireNotNull(apk), fg, onOpenUrl)
                    else -> {
                        Text("Не удалось получить ссылку на актуальную версию.", color = fg, textAlign = TextAlign.Center)
                        TvTextButton(onClick = {
                            loading = true
                            attempt += 1
                        }) { Text("Повторить", color = fg) }
                    }
                }
            }
            TvTextButton(onClick = onDismiss) { Text("Закрыть", color = fg) }
        }
    }
}

@Composable
private fun InstallQr(title: String, url: String, fg: Color, onOpenUrl: (String) -> Unit) {
    val pixels = with(LocalDensity.current) { 208.dp.roundToPx() }
    val bitmap = remember(url, pixels) { qrCodeBitmap(url, pixels)?.asImageBitmap() }
    Column(
        modifier = Modifier.tvClickable(cornerRadius = 12.dp) { onOpenUrl(url) }.padding(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(title, color = fg, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
        if (bitmap != null) {
            Image(
                bitmap = bitmap,
                contentDescription = "QR-код",
                modifier = Modifier.size(236.dp).background(Color.White, RoundedCornerShape(8.dp)).padding(14.dp),
                filterQuality = FilterQuality.None,
            )
        }
    }
}
