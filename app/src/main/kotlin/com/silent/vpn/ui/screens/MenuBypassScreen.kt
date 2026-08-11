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

/** Debug: режимы VK. Olcrtc убран из продукта. */
@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var vkMode by remember { mutableStateOf(repo.getVkCredStrategy()) }
    var pendingVk by remember { mutableStateOf<String?>(null) }
    val vpnRunning = SilentVpnService.isRunning

    LaunchedEffect(Unit) {
        repo.setBypassFamily(SilentRepository.BYPASS_FAMILY_WDTT)
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "bypass",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }

        Text(
            if (BuildConfig.DEBUG) "VK (debug)" else "Обход",
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        if (!BuildConfig.DEBUG) {
            Text(
                "Только VK / WDTT. Другие варианты отключены.",
                fontSize = 12.sp,
                color = fg.copy(alpha = 0.55f),
            )
            return@Column
        }

        if (vpnRunning) {
            Text(
                "Отключите VPN перед сменой режима.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.45f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        BypassOption(
            title = "VKCalls",
            selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_VKCALLS,
            enabled = !vpnRunning,
            fg = fg,
            onSelect = { pendingVk = SilentRepository.VK_CRED_VKCALLS },
        )
        BypassOption(
            title = "Авто капча",
            selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_AUTO,
            enabled = !vpnRunning,
            fg = fg,
            onSelect = { pendingVk = SilentRepository.VK_CRED_AUTO },
        )
        BypassOption(
            title = "Ручная капча",
            selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_MANUAL,
            enabled = !vpnRunning,
            fg = fg,
            onSelect = { pendingVk = SilentRepository.VK_CRED_MANUAL },
        )
    }

    val hasPending = pendingVk != null && pendingVk != vkMode
    if (hasPending) {
        AlertDialog(
            onDismissRequest = { pendingVk = null },
            title = { Text("Применить режим VK?") },
            confirmButton = {
                TvTextButton(onClick = {
                    pendingVk?.let {
                        repo.setVkCredStrategy(it)
                        vkMode = it
                    }
                    pendingVk = null
                }) { Text("Применить") }
            },
            dismissButton = {
                TvTextButton(onClick = { pendingVk = null }) { Text("Отмена") }
            },
        )
    }
}

@Composable
private fun BypassOption(
    title: String,
    selected: Boolean,
    enabled: Boolean,
    fg: Color,
    onSelect: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .tvClickable(enabled = enabled, onClick = onSelect)
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(
            selected = selected,
            onClick = { if (enabled) onSelect() },
            enabled = enabled,
            colors = RadioButtonDefaults.colors(
                selectedColor = fg,
                unselectedColor = fg.copy(alpha = 0.4f),
            ),
        )
        Text(
            title,
            fontSize = 14.sp,
            color = if (enabled) fg else fg.copy(alpha = 0.4f),
            modifier = Modifier.padding(start = 4.dp),
        )
    }
}
