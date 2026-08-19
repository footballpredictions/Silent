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
    var selectedServerSlot by remember { mutableStateOf(SilentRepository.normalizePreferredServer(repo.getPreferredServer())) }
    var pendingServerSlot by remember { mutableStateOf<String?>(null) }
    var applying by remember { mutableStateOf(false) }
    var applyHint by remember { mutableStateOf<String?>(null) }
    var servers by remember { mutableStateOf(fallbackServerList(selectedServerSlot)) }
    val scope = rememberCoroutineScope()
    val switchLocked = applying || vpnState == VpnState.CONNECTING || vpnState == VpnState.CONNECTED

    val hasPending =
        (pendingServerSlot != null && pendingServerSlot != selectedServerSlot)

    LaunchedEffect(Unit) {
        runCatching { repo.fetchVpnServers() }
            .onSuccess { body ->
                if (body.servers.isNotEmpty()) {
                    servers = body.servers
                }
                selectedServerSlot = SilentRepository.normalizePreferredServer(
                    repo.getPreferredServer().ifBlank { body.selected_server },
                )
            }
            .onFailure {
                applyHint = applyHint ?: "Не удалось загрузить список серверов."
            }
    }

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
            servers.forEach { server ->
                val slot = SilentRepository.normalizePreferredServer(server.key)
                BypassOption(
                    title = server.title.ifBlank { slotTitle(slot) },
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
                Text(applyDialogLine(selectedServerSlot, nextServer, servers))
            },
            confirmButton = {
                TvTextButton(onClick = {
                    val nextServer = pendingServerSlot
                    pendingServerSlot = null
                    applyHint = null
                    applying = true
                    scope.launch {
                        try {
                            if (nextServer != null) {
                                runCatching { repo.selectVpnServer(nextServer) }
                                    .onSuccess { body ->
                                        if (body.servers.isNotEmpty()) servers = body.servers
                                    }
                                    .onFailure {
                                        applyHint = "Не удалось применить сервер."
                                    }
                                selectedServerSlot = SilentRepository.normalizePreferredServer(nextServer)
                                repo.setPreferredServer(selectedServerSlot)
                                if (applyHint == null) applyHint = "Выбрано"
                            }
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

private fun slotTitle(slot: String): String {
    val n = SilentRepository.slotFromSelectedServer(slot)?.removePrefix("server")
    return if (n.isNullOrBlank()) slot else "Сервер $n"
}

private fun fallbackServerList(selected: String): List<VpnServerInfo> {
    val maxSlot = SilentRepository.slotFromSelectedServer(selected)
        ?.removePrefix("server")
        ?.toIntOrNull()
        ?: 3
    val n = maxOf(3, maxSlot)
    return (1..n).map { i ->
        VpnServerInfo(
            key = "server$i",
            title = "Сервер $i",
            public_ip = "",
            wdtt_port = 0,
            online_count = 0,
        )
    }
}

private fun applyDialogLine(fromSlot: String, toSlot: String, servers: List<VpnServerInfo>): String {
    fun title(key: String): String =
        servers.firstOrNull { SilentRepository.normalizePreferredServer(it.key) == key }?.title
            ?.ifBlank { null }
            ?: slotTitle(key)
    return if (fromSlot != toSlot) "${title(fromSlot)} → ${title(toSlot)}" else title(toSlot)
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
