package com.silent.vpn.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.HashItemDto
import com.silent.vpn.data.SilentRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun MenuHashesScreen(
    repo: SilentRepository,
    fg: Color,
    onBack: () -> Unit,
) {
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var items by remember { mutableStateOf<List<HashItemDto>>(emptyList()) }

    LaunchedEffect(Unit) {
        loading = true
        error = null
        val res = withContext(Dispatchers.IO) {
            runCatching { repo.getApi().getVpnHashes() }.getOrNull()
        }
        if (res?.isSuccessful == true) {
            items = res.body()?.items.orEmpty()
            if (items.isEmpty()) {
                val hashes = res.body()?.hashes.orEmpty()
                items = hashes.mapIndexed { i, h ->
                    HashItemDto(
                        hash = h,
                        label = if (i == 0) "Bootstrap" else "Сервер #${i - 1}",
                        source = if (i == 0) "bootstrap" else "server",
                        slot_index = if (i == 0) null else i - 1,
                        is_active = true,
                        status = "active",
                    )
                }
            }
        } else {
            error = res?.errorBody()?.string()?.take(120) ?: "Не удалось загрузить хеши"
        }
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
            "Хеши с сервера для VPN-туннеля",
            fontSize = 11.sp,
            color = fg.copy(0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 12.dp),
        )

        when {
            loading -> {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
                }
            }
            error != null -> {
                Text(error!!, fontSize = 12.sp, color = Color(0xFFEF4444))
            }
            items.isEmpty() -> {
                Text("Нет хешей. Добавьте bootstrap на входе или попросите админа.", fontSize = 12.sp, color = fg.copy(0.5f))
            }
            else -> {
                items.forEach { item ->
                    HashRow(item, fg)
                }
            }
        }
    }
}

@Composable
private fun HashRow(item: HashItemDto, fg: Color) {
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
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(item.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg)
                Text(
                    " · $statusText",
                    fontSize = 11.sp,
                    color = if (active) Color(0xFF16A34A) else Color(0xFFEF4444),
                )
            }
            Text(
                item.hash,
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                color = fg.copy(alpha = if (active) 0.65f else 0.35f),
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}
