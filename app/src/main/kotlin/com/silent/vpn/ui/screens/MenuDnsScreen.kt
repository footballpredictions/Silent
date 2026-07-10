package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.util.rememberIsTv

@Composable
fun MenuDnsScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var preset by remember { mutableStateOf(repo.getDnsPreset()) }
    var pending by remember { mutableStateOf<DnsPreset?>(null) }

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TvTextButton(onClick = onBack, requestFocusOnOpen = true, requestFocusKey = "dns") {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
        }

        Text(
            "DNS",
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
            color = fg,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Только debug-сборка. В release DNS всегда с сервера (Яндекс). Применяется при следующем подключении VPN.",
            fontSize = 12.sp,
            color = fg.copy(0.55f),
            modifier = Modifier.padding(bottom = 16.dp),
        )

        if (SilentVpnService.isRunning) {
            Text(
                "Отключите VPN перед сменой DNS.",
                fontSize = 12.sp,
                color = fg.copy(0.7f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        DnsPreset.entries.forEach { option ->
            DnsOptionRow(
                title = option.title,
                subtitle = option.subtitle,
                selected = preset == option,
                enabled = !SilentVpnService.isRunning,
                fg = fg,
                onSelect = { pending = option },
            )
        }
    }

    pending?.let { next ->
        if (next == preset) {
            pending = null
            return@let
        }
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("Сменить DNS?") },
            text = {
                Text(
                    "Было: ${preset.title}\n" +
                        "Будет: ${next.title} (${next.servers})\n\n" +
                        "Переподключите VPN, чтобы применить.",
                )
            },
            confirmButton = {
                TvTextButton(
                    onClick = {
                        repo.setDnsPreset(next)
                        preset = next
                        pending = null
                    },
                ) { Text("Применить") }
            },
            dismissButton = {
                TvTextButton(onClick = { pending = null }) { Text("Отмена") }
            },
        )
    }
}

@Composable
private fun DnsOptionRow(
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
