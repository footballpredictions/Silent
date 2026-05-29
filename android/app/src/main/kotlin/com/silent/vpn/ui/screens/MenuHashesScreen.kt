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
            items.isEmpty() -> {
                Text("Нет хешей. Добавьте bootstrap на входе или попросите админа.", fontSize = 12.sp, color = fg.copy(0.5f))
            }
            else -> {
                if (syncing) {
                    Text("Обновление с сервера…", fontSize = 10.sp, color = fg.copy(0.45f), modifier = Modifier.padding(bottom = 8.dp))
                }
                if (error != null) {
                    Text(error!!, fontSize = 11.sp, color = Color(0xFFEF4444), modifier = Modifier.padding(bottom = 8.dp))
                }
                items.forEach { item ->
                    HashRow(item, fg)
                }
            }
        }
    }
}

private fun formatSavedAt(ts: Long): String {
    val fmt = SimpleDateFormat("dd.MM.yyyy HH:mm", Locale("ru"))
    return fmt.format(Date(ts))
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
