package com.silent.vpn.ui.screens

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.drawable.Drawable
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.util.rememberIsTv
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.ui.theme.ThemePalette
import com.silent.vpn.ui.theme.themeTextFieldColors
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

data class AppItem(
    val name: String,
    val packageName: String,
    val isSystem: Boolean,
    val icon: Drawable?,
)

/** Чисто системное приложение (не обновлялось пользователем из магазина). */
private fun ApplicationInfo.isPureSystemApp(): Boolean =
    (flags and ApplicationInfo.FLAG_SYSTEM) != 0 &&
        (flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP) == 0

private fun loadInstalledApps(pm: PackageManager, selfPackage: String): List<ApplicationInfo> {
    val fromPm = pm.getInstalledApplications(PackageManager.GET_META_DATA)

    val launcherPkgs = runCatching {
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        @Suppress("DEPRECATION")
        pm.queryIntentActivities(intent, PackageManager.MATCH_ALL)
            .mapNotNull { it.activityInfo?.packageName }
            .toSet()
    }.getOrDefault(emptySet())

    val merged = linkedMapOf<String, ApplicationInfo>()
    fromPm.forEach { merged[it.packageName] = it }
    launcherPkgs.forEach { pkg ->
        if (!merged.containsKey(pkg)) {
            runCatching { pm.getApplicationInfo(pkg, PackageManager.GET_META_DATA) }
                .getOrNull()
                ?.let { merged[pkg] = it }
        }
    }
    return merged.values.toList()
}

@Composable
private fun AppIcon(icon: Drawable?, modifier: Modifier = Modifier) {
    val bitmap = remember(icon) {
        runCatching { icon?.toBitmap(96, 96)?.asImageBitmap() }.getOrNull()
    }
    if (bitmap != null) {
        Image(bitmap = bitmap, contentDescription = null, modifier = modifier.size(36.dp))
    } else {
        Box(modifier = modifier.size(36.dp).padding(4.dp))
    }
}

/**
 * Чекбокс: в тёмной теме — чёрный фон, белая галочка, белая рамка квадрата;
 * в светлой — заливка fg, галочка bg, рамка приглушённая.
 */
@Composable
private fun ThemeCheckbox(
    checked: Boolean,
    dark: Boolean,
    fg: Color,
    bg: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    focusable: Boolean = false,
) {
    val border = if (dark) Color.White else fg.copy(alpha = 0.35f)
    val fill = when {
        !checked -> Color.Transparent
        dark -> Color.Black
        else -> fg
    }
    val checkTint = if (dark) Color.White else bg
    val boxMod = if (focusable) {
        modifier
            .size(48.dp)
            .tvClickable(cornerRadius = 6.dp, ringOnly = true, onClick = onClick)
    } else {
        modifier
            .size(24.dp)
            .clickable(onClick = onClick)
    }
    Box(modifier = boxMod, contentAlignment = Alignment.Center) {
        Box(
            modifier = Modifier
                .size(20.dp)
                .clip(RoundedCornerShape(4.dp))
                .border(1.dp, border, RoundedCornerShape(4.dp))
                .background(fill, RoundedCornerShape(4.dp)),
            contentAlignment = Alignment.Center,
        ) {
            if (checked) {
                Icon(
                    Icons.Default.Check,
                    contentDescription = null,
                    tint = checkTint,
                    modifier = Modifier.size(14.dp),
                )
            }
        }
    }
}

@Composable
fun AppExclusionsScreen(
    repo: SilentRepository,
    palette: ThemePalette,
    onBack: () -> Unit,
) {
    val fg = palette.fg
    val bg = palette.bg
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val isTv = rememberIsTv()
    val fieldColors = themeTextFieldColors(palette)
    var apps by remember { mutableStateOf<List<AppItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var search by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(repo.getExcludedPackages()) }
    var showSystemApps by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        loading = true
        apps = withContext(Dispatchers.IO) {
            val pm = context.packageManager
            loadInstalledApps(pm, context.packageName)
                .filter {
                    it.packageName != context.packageName &&
                        !it.packageName.contains("vkontakte") &&
                        !it.packageName.contains("vk.calls")
                }
                .map { info ->
                    AppItem(
                        name = pm.getApplicationLabel(info).toString(),
                        packageName = info.packageName,
                        isSystem = info.isPureSystemApp(),
                        icon = runCatching { pm.getApplicationIcon(info) }.getOrNull(),
                    )
                }
        }
        if (repo.isExclusionsWhitelist()) {
            val all = apps.map { it.packageName }.toSet()
            selected = all - repo.getExcludedPackages()
            repo.saveExcludedApps(selected)
        }
        loading = false
    }

    fun saveSelection(newSelected: Set<String>) {
        selected = newSelected
        repo.saveExcludedApps(newSelected)
        if (WdttTunnelManager.tunnelReady.value) {
            scope.launch { WdttTunnelManager.reloadWireGuard(context) }
        }
    }

    val displayApps = remember(apps, selected, search, showSystemApps) {
        apps
            .asSequence()
            .filter { showSystemApps || !it.isSystem }
            .filter {
                search.isBlank() ||
                    it.name.contains(search, true) ||
                    it.packageName.contains(search, true)
            }
            .sortedWith(
                compareByDescending<AppItem> { selected.contains(it.packageName) }
                    .thenBy { it.name.lowercase() },
            )
            .toList()
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        TvTextButton(onClick = onBack, requestFocusOnOpen = true, requestFocusKey = "exclusions") {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
        }
        Text("Исключения приложений", fontWeight = FontWeight.Bold, fontSize = 14.sp, color = fg)
        Text(
            "Отмеченные приложения идут мимо VPN-туннеля",
            fontSize = 11.sp,
            color = fg.copy(0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )
        Row(
            Modifier.fillMaxWidth().padding(top = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (isTv) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    ThemeCheckbox(
                        checked = showSystemApps,
                        dark = palette.dark,
                        fg = fg,
                        bg = bg,
                        onClick = { showSystemApps = !showSystemApps },
                        focusable = true,
                    )
                    Text(
                        "Показать системные",
                        fontSize = 12.sp,
                        color = fg,
                        modifier = Modifier.padding(start = 4.dp),
                    )
                }
            } else {
                Text("Показать системные", fontSize = 12.sp, color = fg, modifier = Modifier.weight(1f))
                ThemeCheckbox(
                    checked = showSystemApps,
                    dark = palette.dark,
                    fg = fg,
                    bg = bg,
                    onClick = { showSystemApps = !showSystemApps },
                )
            }
        }
        OutlinedTextField(
            value = search,
            onValueChange = { search = it },
            modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
            placeholder = {
                Text("Поиск...", fontSize = 13.sp, color = palette.fieldPlaceholder)
            },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        if (loading) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = fg)
            }
        } else {
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(bottom = 48.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                items(displayApps, key = { it.packageName }) { app ->
                    val checked = selected.contains(app.packageName)
                    val toggle = {
                        saveSelection(
                            if (checked) selected - app.packageName else selected + app.packageName,
                        )
                    }
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .then(
                                if (isTv) {
                                    Modifier.tvClickable(cornerRadius = 10.dp, onClick = toggle)
                                } else {
                                    Modifier.clickable(onClick = toggle)
                                },
                            )
                            .padding(vertical = 6.dp, horizontal = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        AppIcon(app.icon)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f)) {
                            Text(app.name, fontSize = 13.sp, color = fg, maxLines = 1)
                            Text(app.packageName, fontSize = 10.sp, color = fg.copy(0.4f), maxLines = 1)
                        }
                        ThemeCheckbox(
                            checked = checked,
                            dark = palette.dark,
                            fg = fg,
                            bg = bg,
                            onClick = toggle,
                            focusable = isTv,
                        )
                    }
                }
            }
        }
    }
}
