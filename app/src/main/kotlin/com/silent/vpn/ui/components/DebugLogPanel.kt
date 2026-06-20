package com.silent.vpn.ui.components

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.silent.vpn.BuildConfig
import com.silent.vpn.vpn.LogEntry
import com.silent.vpn.vpn.WdttTunnelManager
@Composable
fun DebugLogButton(
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    if (!BuildConfig.DEBUG) return
    TextButton(onClick = onClick, modifier = modifier, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)) {
        Text("Лог", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color(0xFF6B7280))
    }
}

@Composable
fun DebugLogDialog(
    visible: Boolean,
    onDismiss: () -> Unit,
) {
    if (!BuildConfig.DEBUG || !visible) return
    val context = LocalContext.current
    val currentLogs by WdttTunnelManager.logs.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()

    LaunchedEffect(currentLogs.size) {
        if (currentLogs.isNotEmpty()) {
            listState.animateScrollToItem(currentLogs.lastIndex)
        }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Surface(
            modifier = Modifier
                .fillMaxWidth(0.95f)
                .fillMaxHeight(0.85f),
            shape = RoundedCornerShape(16.dp),
            color = Color(0xFF111827),
        ) {
            Column(modifier = Modifier.fillMaxSize()) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Лог VPN",
                        color = Color.White,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.weight(1f),
                    )
                    TextButton(onClick = {
                        val text = currentLogs.joinToString("\n") { "${it.message} (x${it.count})" }
                        copyToClipboard(context, text.ifBlank { "(пусто)" })
                        Toast.makeText(context, "Лог скопирован", Toast.LENGTH_SHORT).show()
                    }) {
                        Text("Копировать", color = Color(0xFF60A5FA), fontSize = 11.sp)
                    }
                    TextButton(onClick = { WdttTunnelManager.clearLogs() }) {
                        Text("Очистить", color = Color(0xFF9CA3AF), fontSize = 11.sp)
                    }
                    TextButton(onClick = onDismiss) {
                        Text("Закрыть", color = Color(0xFF9CA3AF), fontSize = 11.sp)
                    }
                }
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = 12.dp, vertical = 4.dp),
                    contentPadding = PaddingValues(bottom = 12.dp),
                ) {
                    if (currentLogs.isEmpty()) {
                        item {
                            Text(
                                "Лог пуст. Подключите VPN.",
                                color = Color(0xFF9CA3AF),
                                fontSize = 11.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                        }
                    } else {
                        items(currentLogs, key = { it.key }) { entry ->
                            TunnelLogLine(entry)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun TunnelLogLine(entry: LogEntry) {
    val color = when {
        entry.isError -> Color(0xFFEF4444)
        entry.priority <= 2 -> Color(0xFF34D399)
        entry.priority == 3 -> Color(0xFF60A5FA)
        else -> Color(0xFFE5E7EB)
    }

    var trigger by remember { mutableIntStateOf(0) }
    LaunchedEffect(entry.count) { trigger++ }

    val animatedScale by animateFloatAsState(
        targetValue = if (trigger > 0) 1.15f else 1.0f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
        label = "scale",
        finishedListener = { trigger = 0 },
    )

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Surface(
            color = Color(0xFF1E3A5F).copy(alpha = 0.4f),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier
                .defaultMinSize(minWidth = 24.dp, minHeight = 22.dp)
                .graphicsLayer(scaleX = animatedScale, scaleY = animatedScale),
        ) {
            Box(contentAlignment = Alignment.Center, modifier = Modifier.padding(horizontal = 6.dp)) {
                Text(
                    text = "${entry.count}",
                    color = Color(0xFF60A5FA),
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                )
            }
        }
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = entry.message,
            color = color,
            fontSize = 10.sp,
            lineHeight = 14.sp,
            fontFamily = FontFamily.Monospace,
            fontWeight = if (entry.isError) FontWeight.Bold else FontWeight.Normal,
            modifier = Modifier.weight(1f),
        )
    }
}

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("Silent VPN log", text))
}
