package com.silent.vpn.ui.screens

import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class AppItem(val name: String, val packageName: String)

@Composable
fun AppExclusionsScreen(
    repo: SilentRepository,
    fg: Color,
    bg: Color,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var apps by remember { mutableStateOf<List<AppItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var search by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(repo.getExcludedPackages()) }
    var whitelist by remember { mutableStateOf(repo.isExclusionsWhitelist()) }

    LaunchedEffect(Unit) {
        loading = true
        apps = withContext(Dispatchers.IO) {
            val pm = context.packageManager
            pm.getInstalledApplications(PackageManager.GET_META_DATA)
                .filter { it.packageName != context.packageName && !it.packageName.contains("vkontakte") && !it.packageName.contains("vk.calls") }
                .map { AppItem(pm.getApplicationLabel(it).toString(), it.packageName) }
                .sortedBy { it.name.lowercase() }
        }
        loading = false
    }

    fun saveSelection(newSelected: Set<String>, newWhitelist: Boolean = whitelist) {
        selected = newSelected
        whitelist = newWhitelist
        repo.saveExcludedApps(newSelected, newWhitelist)
        if (WdttTunnelManager.tunnelReady.value) {
            scope.launch { WdttTunnelManager.reloadWireGuard(context) }
        }
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        TextButton(onClick = onBack) { Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f)) }
        Text("Исключения приложений", fontWeight = FontWeight.Bold, fontSize = 14.sp, color = fg)
        Text(
            if (whitelist) "БС: неотмеченные идут через VPN" else "ЧС: отмеченные исключены из VPN",
            fontSize = 11.sp,
            color = fg.copy(0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = !whitelist, onClick = {
                if (whitelist) {
                    val all = apps.map { it.packageName }.toSet()
                    saveSelection(all - selected, false)
                }
            }, label = { Text("ЧС") })
            FilterChip(selected = whitelist, onClick = {
                if (!whitelist) {
                    val all = apps.map { it.packageName }.toSet()
                    saveSelection(all - selected, true)
                }
            }, label = { Text("БС") })
        }
        OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            placeholder = { Text("Поиск...", fontSize = 13.sp) },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
        )
        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else {
            val filtered = apps.filter {
                search.isBlank() || it.name.contains(search, true) || it.packageName.contains(search, true)
            }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                items(filtered, key = { it.packageName }) { app ->
                    val checked = selected.contains(app.packageName)
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable {
                                saveSelection(if (checked) selected - app.packageName else selected + app.packageName)
                            }
                            .padding(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(app.name, fontSize = 13.sp, color = fg, maxLines = 1)
                            Text(app.packageName, fontSize = 10.sp, color = fg.copy(0.4f), maxLines = 1)
                        }
                        Checkbox(checked = checked, onCheckedChange = null)
                    }
                }
            }
        }
    }
}
