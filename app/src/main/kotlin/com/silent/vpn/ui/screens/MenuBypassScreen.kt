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
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.WdttTunnelManager

@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    vpnState: VpnState,
    @Suppress("UNUSED_PARAMETER")
    onEnsureBypassApi: suspend (providers: Array<out String>) -> Boolean = { true },
    onBack: () -> Unit,
) {
    var selectedServerSlot by remember { mutableStateOf(slotForSelectedRaw(repo.getPreferredServer())) }
    var pendingServerSlot by remember { mutableStateOf<String?>(null) }
    var applyHint by remember { mutableStateOf<String?>(null) }
    val vpnRuntimeActive = SilentVpnService.isRunning ||
        WdttTunnelManager.running.value ||
        WdttTunnelManager.tunnelReady.value ||
        OlcrtcTunnelManager.running.value ||
        OlcrtcTunnelManager.tunnelReady.value
    val switchLocked = vpnState == VpnState.CONNECTING || vpnRuntimeActive

    val hasPending =
        (pendingServerSlot != null && pendingServerSlot != selectedServerSlot)

    LaunchedEffect(switchLocked) {
        if (switchLocked) {
            pendingServerSlot = null
            applyHint = "Отключите VPN перед сменой сервера."
        } else if (applyHint == "Отключите VPN перед сменой сервера.") {
            applyHint = null
        }
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
            "Выбор сервера",
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        applyHint?.let { hint ->
            Text(
                hint,
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        if (switchLocked) {
            Text(
                "Переключение недоступно: VPN активен.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        Column(Modifier.padding(start = 12.dp)) {
            for (index in 0..2) {
                val slot = "server${index + 1}"
                BypassOption(
                    title = "Сервер ${index + 1}",
                    selected = (pendingServerSlot ?: selectedServerSlot) == slot,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingServerSlot = slot },
                )
            }
        }
    }

    if (hasPending && !switchLocked) {
        AlertDialog(
            onDismissRequest = {
                pendingServerSlot = null
            },
            title = { Text("Применить?") },
            text = {
                val nextServer = pendingServerSlot ?: selectedServerSlot
                val fromIdx = slotIndex(selectedServerSlot)
                val toIdx = slotIndex(nextServer)
                val serverFrom = "Сервер $fromIdx"
                val serverTo = "Сервер $toIdx"
                val line = if (nextServer != selectedServerSlot) {
                    "$serverFrom → $serverTo"
                } else {
                    serverTo
                }
                Text(line)
            },
            confirmButton = {
                TvTextButton(onClick = {
                    val nextServer = pendingServerSlot
                    pendingServerSlot = null
                    if (nextServer != null) {
                        selectedServerSlot = slotForSelectedRaw(nextServer)
                        repo.setPreferredServer(selectedServerSlot)
                        applyHint = "Выбрано"
                    } else {
                        applyHint = null
                    }
                }) { Text("Применить", color = fg) }
            },
            dismissButton = {
                TvTextButton(onClick = {
                    pendingServerSlot = null
                }) { Text("Отмена", color = fg.copy(0.6f)) }
            },
        )
    }
}

private fun slotForSelectedRaw(selectedRaw: String?): String {
    val raw = selectedRaw?.trim()?.lowercase().orEmpty()
    return when (raw) {
        "server2" -> "server2"
        "server3" -> "server3"
        else -> "server1"
    }
}

private fun slotIndex(slot: String): Int =
    when (slot) {
        "server2" -> 2
        "server3" -> 3
        else -> 1
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
