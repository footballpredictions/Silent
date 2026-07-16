package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.util.rememberIsTv
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService

@Composable
fun MenuVkCredModeScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var mode by remember { mutableStateOf(repo.getVkCredStrategy()) }
    var pendingMode by remember { mutableStateOf<String?>(null) }

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TvTextButton(onClick = onBack, requestFocusOnOpen = true, requestFocusKey = "vk-cred") {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
        }

        Text(
            "Режим VK-кредов",
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
            color = fg,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Только debug-сборка. В release всегда VKCalls.",
            fontSize = 12.sp,
            color = fg.copy(0.55f),
            modifier = Modifier.padding(bottom = 16.dp),
        )

        if (SilentVpnService.isRunning) {
            Text(
                "Отключите VPN перед сменой режима.",
                fontSize = 12.sp,
                color = fg.copy(0.7f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        VkCredModeOption(
            title = "VKCalls (по умолчанию)",
            subtitle = "api.vk.me — без капчи, как в proxy-turn-vk-android",
            selected = mode == SilentRepository.VK_CRED_VKCALLS,
            enabled = !SilentVpnService.isRunning,
            fg = fg,
            onSelect = { pendingMode = SilentRepository.VK_CRED_VKCALLS },
        )
        VkCredModeOption(
            title = "Авто капча",
            subtitle = "Запасной режим: 9 воркеров. Legacy + WBV Auto, затем ручной WebView",
            selected = mode == SilentRepository.VK_CRED_AUTO,
            enabled = !SilentVpnService.isRunning,
            fg = fg,
            onSelect = { pendingMode = SilentRepository.VK_CRED_AUTO },
        )
        VkCredModeOption(
            title = "Ручная капча",
            subtitle = "Запасной режим: 9 воркеров. Legacy + только видимый WebView",
            selected = mode == SilentRepository.VK_CRED_MANUAL,
            enabled = !SilentVpnService.isRunning,
            fg = fg,
            onSelect = { pendingMode = SilentRepository.VK_CRED_MANUAL },
        )
    }

    pendingMode?.let { next ->
        if (next == mode) {
            pendingMode = null
            return@let
        }
        AlertDialog(
            onDismissRequest = { pendingMode = null },
            title = { Text("Сменить режим?") },
            text = {
                Text(
                    "Было: ${repo.vkCredStrategyLabel(mode)}\n" +
                        "Будет: ${repo.vkCredStrategyLabel(next)}\n\n" +
                        "Применится при следующем подключении VPN.",
                )
            },
            confirmButton = {
                TvTextButton(
                    onClick = {
                        repo.setVkCredStrategy(next)
                        mode = next
                        pendingMode = null
                    },
                ) { Text("Применить") }
            },
            dismissButton = {
                TvTextButton(onClick = { pendingMode = null }) { Text("Отмена") }
            },
        )
    }
}

@Composable
private fun VkCredModeOption(
    title: String,
    subtitle: String,
    selected: Boolean,
    enabled: Boolean,
    fg: Color,
    onSelect: () -> Unit,
) {
    val isTv = rememberIsTv()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (isTv && enabled) {
                    Modifier.tvClickable(enabled = enabled, onClick = onSelect)
                } else {
                    Modifier
                },
            )
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        RadioButton(
            selected = selected,
            onClick = { if (enabled && !isTv) onSelect() },
            enabled = enabled && !isTv,
        )
        Column(Modifier.padding(start = 4.dp, top = 12.dp)) {
            Text(title, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = fg.copy(if (enabled) 1f else 0.45f))
            Text(subtitle, fontSize = 12.sp, color = fg.copy(if (enabled) 0.6f else 0.35f))
        }
    }
}
