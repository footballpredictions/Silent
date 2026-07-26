package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.BuildConfig
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import kotlinx.coroutines.launch

@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var family by remember { mutableStateOf(repo.getBypassFamily()) }
    var vkMode by remember { mutableStateOf(repo.getVkCredStrategy()) }
    var olcProvider by remember { mutableStateOf(repo.getOlcrtcProvider()) }
    var pendingFamily by remember { mutableStateOf<String?>(null) }
    var pendingVk by remember { mutableStateOf<String?>(null) }
    var pendingOlc by remember { mutableStateOf<String?>(null) }
    var olcCached by remember { mutableStateOf(repo.getCachedOlcrtcConfig() != null) }
    val scope = rememberCoroutineScope()
    val vpnRunning = SilentVpnService.isRunning

    LaunchedEffect(Unit) {
        if (BuildConfig.DEBUG) {
            repo.prefetchOlcrtcConfig()
            olcCached = repo.getCachedOlcrtcConfig() != null
        }
    }

    val effectiveFamily = pendingFamily ?: family

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TvTextButton(onClick = onBack, requestFocusOnOpen = true, requestFocusKey = "bypass") {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
        }

        Text(
            "Варианты обхода",
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
            color = fg,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Только debug. Вход всегда через VK. Здесь — основной VPN. Нужно «Применить».",
            fontSize = 12.sp,
            color = fg.copy(0.55f),
            modifier = Modifier.padding(bottom = 12.dp),
        )
        Text(
            "olcrtc-config: ${if (olcCached) "загружен" else "ещё нет"}",
            fontSize = 12.sp,
            color = fg.copy(0.55f),
            modifier = Modifier.padding(bottom = 12.dp),
        )

        if (vpnRunning) {
            Text(
                "Отключите VPN перед сменой варианта.",
                fontSize = 12.sp,
                color = fg.copy(0.7f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        Text("1. VK / WDTT", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg)
        BypassOption(
            title = "Вариант 1 — VK / WDTT",
            subtitle = "WireGuard через VK TURN",
            selected = effectiveFamily == SilentRepository.BYPASS_FAMILY_WDTT,
            enabled = !vpnRunning,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_WDTT },
        )
        if (effectiveFamily == SilentRepository.BYPASS_FAMILY_WDTT) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "VKCalls",
                    subtitle = "api.vk.me — без капчи",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_VKCALLS,
                    enabled = !vpnRunning,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_VKCALLS },
                )
                BypassOption(
                    title = "Авто капча",
                    subtitle = "Legacy + WBV Auto",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_AUTO,
                    enabled = !vpnRunning,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_AUTO },
                )
                BypassOption(
                    title = "Ручная капча",
                    subtitle = "Legacy + WebView",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_MANUAL,
                    enabled = !vpnRunning,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_MANUAL },
                )
            }
        }

        Spacer(Modifier.height(12.dp))
        Text("2. olcrtc", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg)
        BypassOption(
            title = "Вариант 2 — olcrtc",
            subtitle = "Телемост / WB Stream",
            selected = effectiveFamily == SilentRepository.BYPASS_FAMILY_OLCRTC,
            enabled = !vpnRunning,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_OLCRTC },
        )
        if (effectiveFamily == SilentRepository.BYPASS_FAMILY_OLCRTC) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "Яндекс Телемост",
                    subtitle = "рекомендуется",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_TELEMOST,
                    enabled = !vpnRunning,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_TELEMOST },
                )
                BypassOption(
                    title = "WB Stream",
                    subtitle = "vp8channel",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_WBSTREAM,
                    enabled = !vpnRunning,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_WBSTREAM },
                )
            }
        }
    }

    val hasPending =
        (pendingFamily != null && pendingFamily != family) ||
            (pendingVk != null && pendingVk != vkMode) ||
            (pendingOlc != null && pendingOlc != olcProvider)

    if (hasPending) {
        AlertDialog(
            onDismissRequest = {
                pendingFamily = null
                pendingVk = null
                pendingOlc = null
            },
            title = { Text("Применить?") },
            text = {
                Text(
                    "Семья: ${repo.bypassFamilyLabel(family)}" +
                        (pendingFamily?.let { " → ${repo.bypassFamilyLabel(it)}" } ?: "") +
                        "\nПрименится при следующем подключении.",
                )
            },
            confirmButton = {
                TvTextButton(onClick = {
                    pendingFamily?.let {
                        repo.setBypassFamily(it)
                        family = it
                    }
                    pendingVk?.let {
                        repo.setVkCredStrategy(it)
                        vkMode = it
                    }
                    pendingOlc?.let {
                        repo.setOlcrtcProvider(it)
                        olcProvider = it
                    }
                    pendingFamily = null
                    pendingVk = null
                    pendingOlc = null
                    scope.launch {
                        repo.prefetchOlcrtcConfig()
                        olcCached = repo.getCachedOlcrtcConfig() != null
                    }
                }) { Text("Применить", color = fg) }
            },
            dismissButton = {
                TvTextButton(onClick = {
                    pendingFamily = null
                    pendingVk = null
                    pendingOlc = null
                }) { Text("Отмена", color = fg.copy(0.6f)) }
            },
        )
    }
}

@Composable
private fun BypassOption(
    title: String,
    subtitle: String,
    selected: Boolean,
    enabled: Boolean,
    fg: Color,
    onSelect: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .tvClickable(enabled = enabled, onClick = onSelect)
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        RadioButton(
            selected = selected,
            onClick = if (enabled) onSelect else null,
            enabled = enabled,
            colors = RadioButtonDefaults.colors(selectedColor = fg, unselectedColor = fg.copy(0.4f)),
        )
        Column(Modifier.padding(start = 4.dp)) {
            Text(title, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = fg.copy(if (enabled) 1f else 0.45f))
            Text(subtitle, fontSize = 12.sp, color = fg.copy(0.55f))
        }
    }
}
