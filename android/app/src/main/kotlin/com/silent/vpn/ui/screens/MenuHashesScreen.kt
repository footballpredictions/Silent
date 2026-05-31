package com.silent.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.HashItemDto
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

@Composable
fun MenuHashesScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var loading by remember { mutableStateOf(repo.getSavedHashItems().isEmpty()) }
    var syncing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var items by remember { mutableStateOf(repo.getSavedHashItems()) }
    var savedAt by remember { mutableStateOf(repo.getSavedHashItemsUpdatedAt()) }
    var refreshKey by remember { mutableIntStateOf(0) }
    var channelsPerHash by remember { mutableIntStateOf(repo.getChannelsPerHash()) }

    val activeWorkers by WdttTunnelManager.activeWorkers.collectAsState()
    val vpnRunning by WdttTunnelManager.running.collectAsState()
    val tunnelReady by WdttTunnelManager.tunnelReady.collectAsState()

    val serverItems = items.filter { it.source != "bootstrap" }
    val activeHashCount = serverItems
        .count { it.status == "active" && it.is_active && it.hash.isNotBlank() }
        .coerceIn(1, HashChannelHelper.MAX_HASHES)
    val totalChannels = HashChannelHelper.computeWorkerCount(activeHashCount, channelsPerHash)
    val workersPerHashEst = if (activeHashCount > 0 && vpnRunning) {
        (activeWorkers + activeHashCount - 1) / activeHashCount
    } else {
        0
    }

    suspend fun refreshFromServer() {
        syncing = true
        error = null
        val result = withContext(Dispatchers.IO) { repo.fetchAndSaveHashItems() }
        result.onSuccess { downloaded ->
            if (downloaded.isNotEmpty()) {
                items = downloaded
                savedAt = repo.getSavedHashItemsUpdatedAt()
            } else if (items.isEmpty()) {
                error = "На сервере пока нет хешей"
            }
        }.onFailure {
            if (items.isEmpty()) {
                error = it.message?.take(120) ?: "Не удалось загрузить хеши"
            }
        }
        syncing = false
        loading = false
    }

    LaunchedEffect(refreshKey) {
        if (refreshKey == 0) {
            items = repo.getSavedHashItems()
            savedAt = repo.getSavedHashItemsUpdatedAt()
        }
        refreshFromServer()
    }

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TextButton(onClick = onBack) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
        }
        Text("Хеши", fontWeight = FontWeight.Bold, fontSize = 14.sp, color = fg)
        Text(
            "Сохранены на устройстве и обновляются с сервера",
            fontSize = 11.sp,
            color = fg.copy(0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 4.dp),
        )
        if (savedAt > 0L) {
            Text(
                "Последнее обновление: ${formatSavedAt(savedAt)}",
                fontSize = 10.sp,
                color = fg.copy(0.4f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        ChannelStrengthSelector(
            fg = fg,
            selected = channelsPerHash,
            activeHashCount = activeHashCount,
            totalChannels = totalChannels,
            onSelect = { value ->
                channelsPerHash = value
                repo.saveChannelsPerHash(value)
            },
        )

        if (SilentVpnService.isRunning && tunnelReady) {
            Text(
                "Активных каналов: $activeWorkers / $totalChannels",
                fontSize = 10.sp,
                color = fg.copy(0.55f),
                modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
            )
        } else {
            Spacer(Modifier.height(8.dp))
        }

        TextButton(
            onClick = { refreshKey++ },
            enabled = !syncing,
            modifier = Modifier.padding(bottom = 4.dp),
        ) {
            Text(if (syncing) "Обновление…" else "Обновить с сервера", fontSize = 11.sp, color = fg.copy(0.7f))
        }

        when {
            loading -> {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
            error != null && items.isEmpty() -> {
                Text(error!!, fontSize = 12.sp, color = Color(0xFFEF4444))
            }
            serverItems.isEmpty() -> {
                Text("Нет серверных хешей. Попросите админа выдать слоты.", fontSize = 12.sp, color = fg.copy(0.5f))
            }
            else -> {
                if (syncing) {
                    Text("Обновление с сервера…", fontSize = 10.sp, color = fg.copy(0.45f), modifier = Modifier.padding(bottom = 8.dp))
                }
                if (error != null) {
                    Text(error!!, fontSize = 11.sp, color = Color(0xFFEF4444), modifier = Modifier.padding(bottom = 8.dp))
                }
                serverItems.forEach { item ->
                    HashRow(
                        item = item,
                        fg = fg,
                        signalBars = if (vpnRunning && item.status == "active" && item.is_active) {
                            HashChannelHelper.signalBars(workersPerHashEst, channelsPerHash)
                        } else {
                            0
                        },
                        channelsPerHash = channelsPerHash,
                    )
                }
            }
        }
    }
}

@Composable
private fun ChannelStrengthSelector(
    fg: Color,
    selected: Int,
    activeHashCount: Int,
    totalChannels: Int,
    onSelect: (Int) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(1.dp, fg.copy(0.12f), RoundedCornerShape(12.dp))
            .padding(12.dp),
    ) {
        Text("Сила каналов", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = fg)
        Text(
            "$activeHashCount хеш(а) × $selected = $totalChannels потоков (макс. ${HashChannelHelper.computeWorkerCount(activeHashCount, 27)})",
            fontSize = 10.sp,
            color = fg.copy(0.5f),
            modifier = Modifier.padding(top = 2.dp, bottom = 8.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            HashChannelHelper.OPTIONS.forEach { option ->
                val picked = selected == option
                val total = HashChannelHelper.computeWorkerCount(activeHashCount, option)
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (picked) fg else fg.copy(0.08f))
                        .clickable { onSelect(option) }
                        .padding(vertical = 6.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            "$total",
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold,
                            color = if (picked) Color.White else fg,
                        )
                        Text(
                            "$option/хеш",
                            fontSize = 9.sp,
                            color = if (picked) Color.White.copy(0.85f) else fg.copy(0.45f),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SignalBars(bars: Int, fg: Color, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier,
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.Bottom,
    ) {
        repeat(4) { i ->
            val filled = i < bars
            Box(
                Modifier
                    .width(3.dp)
                    .height((6 + i * 3).dp)
                    .clip(RoundedCornerShape(1.dp))
                    .background(if (filled) Color(0xFF22C55E) else fg.copy(0.15f)),
            )
        }
    }
}

private fun formatSavedAt(ts: Long): String {
    val fmt = SimpleDateFormat("dd.MM.yyyy HH:mm", Locale("ru"))
    return fmt.format(Date(ts))
}

@Composable
private fun HashRow(
    item: HashItemDto,
    fg: Color,
    signalBars: Int,
    channelsPerHash: Int,
) {
    val active = item.status == "active" && item.is_active
    val lamp = if (active) Color(0xFF22C55E) else Color(0xFFEF4444)
    val statusText = if (active) "Активна" else "Просрочен"

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Box(
            modifier = Modifier
                .padding(top = 4.dp)
                .size(8.dp)
                .background(lamp, CircleShape),
        )
        Column(modifier = Modifier.padding(start = 10.dp).weight(1f)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg)
                    Text(
                        " · $statusText",
                        fontSize = 11.sp,
                        color = if (active) Color(0xFF16A34A) else Color(0xFFEF4444),
                    )
                }
                if (active && signalBars > 0) {
                    SignalBars(bars = signalBars, fg = fg)
                }
            }
            Text(
                item.hash,
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                color = fg.copy(alpha = if (active) 0.65f else 0.35f),
                modifier = Modifier.padding(top = 4.dp),
            )
            if (active) {
                Text(
                    "до $channelsPerHash каналов",
                    fontSize = 9.sp,
                    color = fg.copy(0.4f),
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
    }
}
