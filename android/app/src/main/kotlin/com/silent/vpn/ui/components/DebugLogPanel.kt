package com.silent.vpn.ui.components

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.silent.vpn.util.DebugLog

@Composable
fun DebugLogButton(
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
) {
    TextButton(onClick = onClick, modifier = modifier, contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp)) {
        Text("Лог", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color(0xFF6B7280))
    }
}

@Composable
fun DebugLogDialog(
    visible: Boolean,
    onDismiss: () -> Unit,
) {
    if (!visible) return
    val context = LocalContext.current
    val logText by DebugLog.text.collectAsState()
    val scroll = rememberScrollState()

    LaunchedEffect(logText) {
        scroll.animateScrollTo(scroll.maxValue)
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
                        .background(Color(0xFF1F2937))
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("Лог VPN (debug)", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                    TextButton(onClick = {
                        copyToClipboard(context, logText.ifBlank { "(пусто)" })
                        Toast.makeText(context, "Лог скопирован", Toast.LENGTH_SHORT).show()
                    }) {
                        Text("Копировать", color = Color(0xFF60A5FA), fontSize = 11.sp)
                    }
                    TextButton(onClick = { DebugLog.clear() }) {
                        Text("Очистить", color = Color(0xFF9CA3AF), fontSize = 11.sp)
                    }
                    TextButton(onClick = onDismiss) {
                        Text("Закрыть", color = Color(0xFF9CA3AF), fontSize = 11.sp)
                    }
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(8.dp)
                        .verticalScroll(scroll),
                ) {
                    Text(
                        text = logText.ifBlank { "Лог пуст. Подключите VPN или привяжите VK." },
                        color = Color(0xFFE5E7EB),
                        fontSize = 10.sp,
                        lineHeight = 14.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }
    }
}

private fun copyToClipboard(context: Context, text: String) {
    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    cm.setPrimaryClip(ClipData.newPlainText("Silent VPN log", text))
}
