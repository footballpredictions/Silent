package com.silent.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Slider
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

    val activeWorkers by WdttTunnelManager.activeWorkers.collectAsState()
    val vpnRunning by WdttTunnelManager.running.collectAsState()
    val tunnelReady by WdttTunnelManager.tunnelReady.collectAsState()

    val serverItems = items.filter { it.source != "bootstrap" }
    val activeHashCount = serverItems
        .count { it.status == "active" && it.is_active && it.hash.isNotBlank() }
        .coerceIn(1, HashChannelHelper.MAX_HASHES)
    val maxTotalWorkers = HashChannelHelper.maxTotalWorkers(activeHashCount)
    var totalWorkers by remember(activeHashCount) {
        mutableIntStateOf(repo.getTotalWorkers(activeHashCount))
    }

    LaunchedEffect(activeHashCount) {
        val normalized = repo.getTotalWorkers(activeHashCount)
        if (totalWorkers != normalized) totalWorkers = normalized
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
            totalWorkers = totalWorkers,
            activeHashCount = activeHashCount,
            maxTotalWorkers = maxTotalWorkers,
            vpnRunning = SilentVpnService.isRunning,
            onSelect = { value ->
                totalWorkers = value
                repo.saveTotalWorkers(value, activeHashCount)
            },
        )

        if (SilentVpnService.isRunning && tunnelReady) {
            Text(
                "Активных каналов: $activeWorkers / $totalWorkers",
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
                serverItems.forEachIndexed { index, item ->
                    HashRow(
                        item = item,
                        fg = fg,
                        signalBars = if (vpnRunning && item.status == "active" && item.is_active) {
                            HashChannelHelper.signalBars(activeWorkers, totalWorkers)
                        } else {
                            0
                        },
                        maxChannels = HashChannelHelper.workersForHashSlot(
                            totalWorkers,
                            index,
                            activeHashCount,
                        ),
                    )
                }
            }
        }
    }
}

@Composable
private fun ChannelStrengthSelector(
    fg: Color,
    totalWorkers: Int,
    activeHashCount: Int,
    maxTotalWorkers: Int,
    vpnRunning: Boolean,
    onSelect: (Int) -> Unit,
) {
    val min = HashChannelHelper.WORKERS_PER_GROUP.toFloat()
    val max = maxTotalWorkers.toFloat()
    val stepped = HashChannelHelper.normalizeTotalWorkers(totalWorkers, activeHashCount)
    val sliderSteps = ((maxTotalWorkers / HashChannelHelper.WORKERS_PER_GROUP) - 1).coerceAtLeast(0)
    val muted = fg.copy(alpha = 0.5f)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(1.dp, fg.copy(0.12f), RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 12.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Сила каналов", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = fg)
            Text(
                stepped.toString(),
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                color = fg,
            )
        }
        Text(
            "Потоков: $stepped из $maxTotalWorkers (шаг 9, до $activeHashCount хеш × 27)",
            fontSize = 10.sp,
            color = muted,
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
        )
        Slider(
            value = stepped.toFloat(),
            onValueChange = { raw ->
                onSelect(HashChannelHelper.normalizeTotalWorkers(raw.toInt(), activeHashCount))
            },
            valueRange = min..max,
            steps = sliderSteps,
            enabled = !vpnRunning,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            "9 → 18 → 27 → 36… (шаг 9, макс $maxTotalWorkers = $activeHashCount хеш × 27)",
            fontSize = 9.sp,
            color = muted,
            modifier = Modifier.padding(top = 8.dp),
        )
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
    maxChannels: Int,
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
                    if (maxChannels > 0) {
                        "$maxChannels / ${HashChannelHelper.MAX_WORKERS_PER_HASH} каналов"
                    } else {
                        "0 / ${HashChannelHelper.MAX_WORKERS_PER_HASH} каналов · увеличьте потоки"
                    },
                    fontSize = 9.sp,
                    color = fg.copy(0.4f),
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }
    }
}
