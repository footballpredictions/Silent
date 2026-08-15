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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.VpnServerInfo
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import kotlinx.coroutines.launch

@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    vpnState: VpnState,
    @Suppress("UNUSED_PARAMETER")
    onEnsureBypassApi: suspend (providers: Array<out String>) -> Boolean = { true },
    onBack: () -> Unit,
) {
    var selectedServerSlot by remember { mutableStateOf(slotForSelectedRaw(repo.getPreferredServer(), emptyList())) }
    var servers by remember { mutableStateOf<List<VpnServerInfo>>(emptyList()) }
    var pendingServerSlot by remember { mutableStateOf<String?>(null) }
    var applying by remember { mutableStateOf(false) }
    var applyHint by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val switchLocked = applying || vpnState != VpnState.DISCONNECTED

    LaunchedEffect(Unit) {
        runCatching { repo.fetchVpnServers() }
            .onSuccess { data ->
                servers = data.servers
                selectedServerSlot = slotForSelectedRaw(data.selected_server, data.servers)
                repo.setPreferredServer(selectedServerSlot)
            }
            .onFailure {
                applyHint = "Не удалось загрузить список серверов."
            }
    }

    val hasPending =
        (pendingServerSlot != null && pendingServerSlot != selectedServerSlot)

    LaunchedEffect(vpnState) {
        if (vpnState != VpnState.DISCONNECTED) {
            pendingServerSlot = null
            applyHint = "Отключите VPN перед сменой сервера."
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

        if (vpnState != VpnState.DISCONNECTED) {
            Text(
                "Переключение недоступно: VPN активен.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        Column(Modifier.padding(start = 12.dp)) {
            val availableSlots = servers.take(3)
            for (index in 0..2) {
                val slot = "server${index + 1}"
                val enabledSlot = availableSlots.getOrNull(index) != null
                BypassOption(
                    title = "Сервер ${index + 1}",
                    selected = (pendingServerSlot ?: selectedServerSlot) == slot,
                    enabled = !switchLocked && enabledSlot,
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
                    applyHint = null
                    applying = true
                    scope.launch {
                        try {
                            nextServer?.let { key ->
                                val selected = runCatching { repo.selectVpnServer(key) }
                                    .getOrNull()
                                selectedServerSlot = slotForSelectedRaw(selected?.selected_server, selected?.servers ?: servers)
                                repo.setPreferredServer(selectedServerSlot)
                            }
                            runCatching { repo.fetchVpnServers() }
                                .onSuccess { data ->
                                    servers = data.servers
                                    selectedServerSlot = slotForSelectedRaw(data.selected_server, data.servers)
                                    repo.setPreferredServer(selectedServerSlot)
                                }
                            applyHint = "Выбрано"
                        } finally {
                            applying = false
                        }
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

private fun slotForSelectedRaw(selectedRaw: String?, servers: List<VpnServerInfo>): String {
    val raw = selectedRaw?.trim()?.lowercase().orEmpty()
    if (raw == "server1" || raw == "server2" || raw == "server3") return raw
    val idx = servers.indexOfFirst { it.key == raw }
    return when (idx) {
        1 -> "server2"
        2 -> "server3"
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
