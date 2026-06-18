package com.silent.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import com.silent.vpn.ui.components.PcStyleRangeSlider
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
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalDensity
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.HashItemDto
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.theme.UiColors
import com.silent.vpn.ui.theme.UiDimens
import com.silent.vpn.vpn.WdttTunnelManager
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
    var items by remember { mutableStateOf(repo.getSavedHashItems()) }
    var savedAt by remember { mutableStateOf(repo.getSavedHashItemsUpdatedAt()) }

    val activeWorkers by WdttTunnelManager.activeWorkers.collectAsState()
    val vpnRunning by WdttTunnelManager.running.collectAsState()
    val tunnelReady by WdttTunnelManager.tunnelReady.collectAsState()

    val serverItems = items.filter { it.source != "bootstrap" }
    val activeHashCount = serverItems
        .count { it.status == "active" && it.is_active && it.hash.isNotBlank() }
        .coerceIn(0, HashChannelHelper.MAX_HASHES)
        .coerceAtLeast(1)
    val maxTotalWorkers = HashChannelHelper.maxTotalWorkers(activeHashCount)
    var totalWorkers by remember(activeHashCount) {
        mutableIntStateOf(repo.getTotalWorkers(activeHashCount))
    }

    LaunchedEffect(activeHashCount) {
        val normalized = repo.getTotalWorkers(activeHashCount)
        if (totalWorkers != normalized) totalWorkers = normalized
    }

    LaunchedEffect(Unit) {
        items = repo.getSavedHashItems()
        savedAt = repo.getSavedHashItemsUpdatedAt()
        loading = false
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
            "Кеш на устройстве. При подключении VPN список обновляется автоматически.",
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

        when {
            loading -> {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
            serverItems.isEmpty() -> {
                Text("Нет серверных хешей. Подключите VPN или попросите админа выдать слоты.", fontSize = 12.sp, color = fg.copy(0.5f))
            }
            else -> {
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
    val stepped = HashChannelHelper.normalizeTotalWorkers(totalWorkers, activeHashCount)
    val muted = fg.copy(alpha = 0.5f)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .border(UiDimens.borderThin, fg.copy(alpha = 0.12f), RoundedCornerShape(12.dp))
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
            "Потоков: $stepped из $maxTotalWorkers (шаг 9, макс $activeHashCount хеша × 27)",
            fontSize = 10.sp,
            color = muted,
            modifier = Modifier.padding(top = 4.dp, bottom = 4.dp),
        )
        Text(
            if (vpnRunning) {
                "Чтобы применить: выключите VPN → выберите силу → подключите снова (смотрите «Активных каналов»)"
            } else {
                "После смены переподключите VPN. Скорость теста часто упирается в VPS/сеть; каналы дают запас и стабильность"
            },
            fontSize = 9.sp,
            color = muted,
            modifier = Modifier.padding(bottom = 12.dp),
        )
        PcStyleRangeSlider(
            value = stepped,
            onValueChange = { onSelect(HashChannelHelper.normalizeTotalWorkers(it, activeHashCount)) },
            minValue = HashChannelHelper.WORKERS_PER_GROUP,
            maxValue = maxTotalWorkers,
            step = HashChannelHelper.WORKERS_PER_GROUP,
            enabled = !vpnRunning,
            accent = fg,
        )
        Text(
            "В логе connect: n=$stepped — столько воркеров запустит libclient",
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
    val fmt = SimpleDateFormat("dd.MM.yyyy HH:mm", Locale.forLanguageTag("ru"))
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

    val density = LocalDensity.current
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .drawBehind {
                val stroke = with(density) { UiDimens.borderThin.toPx() }
                drawLine(
                    color = UiColors.Gray100,
                    start = Offset(0f, size.height - (stroke / 2f)),
                    end = Offset(size.width, size.height - (stroke / 2f)),
                    strokeWidth = stroke,
                )
            }
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
