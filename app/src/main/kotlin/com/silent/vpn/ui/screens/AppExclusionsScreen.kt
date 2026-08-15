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
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvPrimaryButton
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
import com.silent.vpn.vpn.SiteBypassRoutes
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

private enum class ExclusionsPane { Sites, Apps }

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
private fun ModeChip(
    label: String,
    active: Boolean,
    fg: Color,
    bg: Color,
    onClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(if (active) fg else Color.Transparent)
            .border(1.dp, if (active) fg else fg.copy(0.25f), RoundedCornerShape(8.dp))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Text(label, fontSize = 12.sp, color = if (active) bg else fg)
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

    var pane by remember { mutableStateOf(ExclusionsPane.Apps) }

    // —— Apps ——
    var apps by remember { mutableStateOf<List<AppItem>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var search by remember { mutableStateOf("") }
    var selected by remember { mutableStateOf(repo.getExcludedPackages()) }
    var whitelist by remember { mutableStateOf(repo.isExclusionsWhitelist()) }
    var showSystemApps by remember { mutableStateOf(false) }

    // —— Sites ——
    var siteRules by remember {
        mutableStateOf(SiteBypassRoutes.limitRules(SiteBypassRoutes.parseRules(repo.getBypassRoutesRaw())))
    }
    var newRule by remember { mutableStateOf("") }
    var siteHint by remember { mutableStateOf<String?>(null) }
    var siteBusy by remember { mutableStateOf(false) }

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
        loading = false
    }

    fun reloadTunnel() {
        if (WdttTunnelManager.tunnelReady.value) {
            scope.launch { WdttTunnelManager.reloadWireGuard(context) }
        }
    }

    fun saveAppSelection(newSelected: Set<String>, newWhitelist: Boolean = whitelist) {
        selected = newSelected
        whitelist = newWhitelist
        repo.saveExcludedApps(newSelected, newWhitelist)
        reloadTunnel()
    }

    fun switchMode(toWhitelist: Boolean) {
        if (whitelist == toWhitelist) return
        val next = emptySet<String>()
        repo.saveExceptionsMode(toWhitelist, next)
        selected = next
        whitelist = toWhitelist
        reloadTunnel()
    }

    fun persistSites(rules: List<String>) {
        scope.launch {
            siteBusy = true
            siteHint = null
            try {
                val capped = SiteBypassRoutes.limitRules(rules)
                repo.saveBypassRoutes(capped.joinToString("\n"))
                SiteBypassRoutes.clearResolveCache()
                siteRules = capped
                val result = withContext(Dispatchers.IO) {
                    SiteBypassRoutes.resolveExcludeTargets(capped.joinToString("\n"))
                }
                siteHint = when {
                    result.unresolved.isNotEmpty() ->
                        "Не резолвится: ${result.unresolved.take(2).joinToString()}"
                    result.truncated -> "Список урезан — слишком много адресов"
                    else -> result.resolvedPreview.firstOrNull()
                }
                reloadTunnel()
            } catch (e: Exception) {
                siteHint = "Ошибка: ${e.message}"
            } finally {
                siteBusy = false
            }
        }
    }

    fun addSiteRule() {
        val rule = SiteBypassRoutes.normalizeRuleInput(newRule)
        if (rule.isEmpty() || siteBusy) return
        if (siteRules.any { it.equals(rule, ignoreCase = true) }) {
            siteHint = "Уже в списке"
            newRule = ""
            return
        }
        if (siteRules.size >= SiteBypassRoutes.MAX_RULES) {
            siteHint = "Лимит ${SiteBypassRoutes.MAX_RULES} сайтов"
            return
        }
        newRule = ""
        persistSites(siteRules + rule)
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
        Text("Исключения", fontWeight = FontWeight.Bold, fontSize = 14.sp, color = fg)

        Row(
            Modifier.padding(top = 10.dp, bottom = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            ModeChip(
                label = "Сайты",
                active = pane == ExclusionsPane.Sites,
                fg = fg,
                bg = bg,
                onClick = { pane = ExclusionsPane.Sites },
            )
            ModeChip(
                label = "Приложения",
                active = pane == ExclusionsPane.Apps,
                fg = fg,
                bg = bg,
                onClick = { pane = ExclusionsPane.Apps },
            )
        }

        when (pane) {
            ExclusionsPane.Sites -> {
                Text(
                    "Домен или IP идут мимо VPN (ozon.ru, 1.2.3.4, 10.0.0.0/8)",
                    fontSize = 11.sp,
                    color = fg.copy(0.5f),
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                OutlinedTextField(
                    value = newRule,
                    onValueChange = { newRule = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = {
                        Text("домен или IP…", fontSize = 13.sp, color = palette.fieldPlaceholder)
                    },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    colors = fieldColors,
                    enabled = !siteBusy,
                )
                TvPrimaryButton(
                    onClick = { addSiteRule() },
                    enabled = !siteBusy && newRule.isNotBlank(),
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = palette.primaryBtnBg,
                        contentColor = palette.primaryBtnFg,
                        disabledContainerColor = palette.primaryBtnBg.copy(alpha = 0.4f),
                        disabledContentColor = palette.primaryBtnFg.copy(alpha = 0.5f),
                    ),
                ) {
                    Text("Добавить", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                }
                siteHint?.let {
                    Text(
                        it,
                        fontSize = 11.sp,
                        color = fg.copy(0.55f),
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
                Text(
                    "${siteRules.size} / ${SiteBypassRoutes.MAX_RULES}",
                    fontSize = 10.sp,
                    color = fg.copy(0.4f),
                    modifier = Modifier.padding(top = 4.dp, bottom = 6.dp),
                )
                if (siteRules.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            "Список пуст\nДобавьте домен или IP",
                            fontSize = 13.sp,
                            color = fg.copy(0.45f),
                        )
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.weight(1f),
                        contentPadding = PaddingValues(bottom = 48.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        items(siteRules, key = { it }) { rule ->
                            Row(
                                Modifier
                                    .fillMaxWidth()
                                    .padding(vertical = 8.dp, horizontal = 4.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(rule, fontSize = 13.sp, color = fg, modifier = Modifier.weight(1f))
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "Удалить",
                                    tint = fg.copy(0.5f),
                                    modifier = Modifier
                                        .size(20.dp)
                                        .clickable(enabled = !siteBusy) {
                                            persistSites(siteRules.filterNot { it == rule })
                                        },
                                )
                            }
                        }
                    }
                }
            }

            ExclusionsPane.Apps -> {
                Text(
                    if (whitelist) "БС: только выбранные через VPN"
                    else "ЧС: выбранные мимо VPN",
                    fontSize = 11.sp,
                    color = fg.copy(0.5f),
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ModeChip(
                        label = "ЧС",
                        active = !whitelist,
                        fg = fg,
                        bg = bg,
                        onClick = { switchMode(false) },
                    )
                    ModeChip(
                        label = "БС",
                        active = whitelist,
                        fg = fg,
                        bg = bg,
                        onClick = { switchMode(true) },
                    )
                }
                Row(
                    Modifier.fillMaxWidth().padding(top = 8.dp),
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
                val visiblePackages = displayApps.map { it.packageName }.toSet()
                val allVisibleSelected =
                    visiblePackages.isNotEmpty() && visiblePackages.all { selected.contains(it) }
                Row(
                    Modifier.fillMaxWidth().padding(top = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    fun toggleAll() {
                        if (visiblePackages.isEmpty()) return
                        saveAppSelection(
                            if (allVisibleSelected) selected - visiblePackages else selected + visiblePackages,
                        )
                    }
                    if (isTv) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            ThemeCheckbox(
                                checked = allVisibleSelected,
                                dark = palette.dark,
                                fg = fg,
                                bg = bg,
                                onClick = { toggleAll() },
                                focusable = true,
                            )
                            Text(
                                "Выделить все",
                                fontSize = 12.sp,
                                color = fg.copy(alpha = if (visiblePackages.isNotEmpty()) 1f else 0.45f),
                                modifier = Modifier.padding(start = 4.dp),
                            )
                        }
                    } else {
                        Text("Выделить все", fontSize = 12.sp, color = fg, modifier = Modifier.weight(1f))
                        ThemeCheckbox(
                            checked = allVisibleSelected,
                            dark = palette.dark,
                            fg = fg,
                            bg = bg,
                            onClick = { toggleAll() },
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
                                saveAppSelection(
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
    }
}
