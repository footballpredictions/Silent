package com.silent.vpn.ui.screens

import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.graphics.drawable.Drawable
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.filled.FileUpload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvIconButton
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
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

@Composable
private fun SiteImportExportActions(
    siteBusy: Boolean,
    canExport: Boolean,
    palette: ThemePalette,
    onImport: () -> Unit,
    onExport: () -> Unit,
) {
    Row {
        IconButton(onClick = onImport, enabled = !siteBusy) {
            Icon(
                Icons.Default.FileUpload,
                contentDescription = "Импорт списка",
                tint = palette.fg.copy(alpha = if (siteBusy) 0.35f else 0.55f),
                modifier = Modifier.size(20.dp),
            )
        }
        IconButton(onClick = onExport, enabled = !siteBusy && canExport) {
            Icon(
                Icons.Default.FileDownload,
                contentDescription = "Экспорт списка",
                tint = palette.fg.copy(alpha = if (!siteBusy && canExport) 0.55f else 0.35f),
                modifier = Modifier.size(20.dp),
            )
        }
    }
}

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
    var blacklistApps by remember { mutableStateOf(repo.getBlacklistPackages()) }
    var whitelistApps by remember { mutableStateOf(repo.getWhitelistPackages()) }
    var showSystemApps by remember { mutableStateOf(false) }

    // —— Sites ——
    var siteRules by remember {
        mutableStateOf(SiteBypassRoutes.limitRules(SiteBypassRoutes.parseRules(repo.getBypassRoutesRaw())))
    }
    var newRule by remember { mutableStateOf("") }
    var siteHint by remember { mutableStateOf<String?>(null) }
    var siteBusy by remember { mutableStateOf(false) }
    var editingRule by remember { mutableStateOf<String?>(null) }
    var editDraft by remember { mutableStateOf("") }

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
        if (newWhitelist) whitelistApps = newSelected else blacklistApps = newSelected
        repo.saveExcludedApps(newSelected, newWhitelist)
        reloadTunnel()
    }

    fun switchMode(toWhitelist: Boolean) {
        if (whitelist == toWhitelist) return
        val next = if (toWhitelist) whitelistApps else blacklistApps
        repo.saveExceptionsMode(toWhitelist)
        selected = next
        whitelist = toWhitelist
        reloadTunnel()
    }

    fun persistSites(rules: List<String>, hintOverride: String? = null) {
        scope.launch {
            siteBusy = true
            siteHint = null
            try {
                val capped = SiteBypassRoutes.limitRules(rules)
                repo.saveBypassRoutes(capped.joinToString("\n"))
                SiteBypassRoutes.clearResolveCache()
                siteRules = capped
                withContext(Dispatchers.IO) {
                    val dnsNet = VpnNetworkHelper.findUnderlyingNetwork(context)
                    SiteBypassRoutes.resolveExcludeTargets(capped.joinToString("\n"), dnsNet)
                }
                // Как на PC: без списка IP в UI после добавления.
                siteHint = hintOverride
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

    fun saveSiteEdit(original: String) {
        val next = SiteBypassRoutes.normalizeRuleInput(editDraft)
        editingRule = null
        if (next.isEmpty() || siteBusy) return
        if (next.equals(original, ignoreCase = true)) return
        if (siteRules.any { it.equals(next, ignoreCase = true) && !it.equals(original, ignoreCase = true) }) {
            siteHint = "Уже в списке"
            return
        }
        persistSites(siteRules.map { if (it == original) next else it })
    }

    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            try {
                val content = withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)?.use { stream ->
                        stream.bufferedReader().readText()
                    }.orEmpty()
                }
                val imported = SiteBypassRoutes.extractRulesFromImportContent(content)
                val before = siteRules.size
                val merged = SiteBypassRoutes.mergeImportRules(siteRules, imported)
                if (merged.size == before) {
                    siteHint = "Новых правил не найдено"
                } else {
                    persistSites(merged, "Импорт: +${merged.size - before} правил")
                }
            } catch (e: Exception) {
                siteHint = "Ошибка импорта: ${e.message}"
            }
        }
    }

    val exportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json"),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch(Dispatchers.IO) {
            try {
                val payload = JSONObject()
                    .put("version", 1)
                    .put("rules", JSONArray(siteRules))
                    .toString(2)
                context.contentResolver.openOutputStream(uri)?.use { out ->
                    out.write(payload.toByteArray(Charsets.UTF_8))
                }
                withContext(Dispatchers.Main) {
                    siteHint = "Экспорт: ${siteRules.size} правил"
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    siteHint = "Ошибка экспорта: ${e.message}"
                }
            }
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
    val appsListState = remember(whitelist) { LazyListState() }

    LaunchedEffect(whitelist, loading) {
        if (!loading && displayApps.isNotEmpty()) {
            appsListState.scrollToItem(0)
        }
    }

    if (editingRule != null) {
        AlertDialog(
            onDismissRequest = { if (!siteBusy) editingRule = null },
            title = { Text("Изменить правило", fontSize = 14.sp) },
            text = {
                OutlinedTextField(
                    value = editDraft,
                    onValueChange = { editDraft = it },
                    placeholder = {
                        Text("домен или IP…", color = palette.fieldPlaceholder)
                    },
                    singleLine = true,
                    enabled = !siteBusy,
                    modifier = Modifier.fillMaxWidth(),
                    colors = fieldColors,
                )
            },
            confirmButton = {
                TvTextButton(
                    enabled = !siteBusy && editDraft.isNotBlank(),
                    onClick = {
                        val original = editingRule ?: return@TvTextButton
                        saveSiteEdit(original)
                    },
                ) { Text("Сохранить") }
            },
            dismissButton = {
                TvTextButton(onClick = { if (!siteBusy) editingRule = null }) {
                    Text("Отмена")
                }
            },
        )
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TvTextButton(onClick = onBack, requestFocusOnOpen = true, requestFocusKey = "exclusions") {
                Text("← Назад", fontSize = 12.sp, color = fg.copy(0.5f))
            }
            if (pane == ExclusionsPane.Sites) {
                SiteImportExportActions(
                    siteBusy = siteBusy,
                    canExport = siteRules.isNotEmpty(),
                    palette = palette,
                    onImport = { importLauncher.launch(arrayOf("*/*")) },
                    onExport = { exportLauncher.launch("site-exclusions.json") },
                )
            }
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
                    trailingIcon = {
                        if (newRule.isNotBlank()) {
                            IconButton(onClick = { newRule = "" }, enabled = !siteBusy) {
                                Icon(
                                    Icons.Default.Close,
                                    contentDescription = "Очистить",
                                    tint = fg.copy(alpha = 0.55f),
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                        }
                    },
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
                    modifier = Modifier.padding(top = 8.dp, bottom = 6.dp),
                )
                if (siteRules.isEmpty()) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text(
                            "Список пуст",
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
                                Text(
                                    rule,
                                    fontSize = 13.sp,
                                    color = fg,
                                    modifier = Modifier.weight(1f),
                                )
                                TvIconButton(
                                    onClick = {
                                        editingRule = rule
                                        editDraft = rule
                                    },
                                    enabled = !siteBusy,
                                    modifier = Modifier.size(32.dp),
                                ) {
                                    Icon(
                                        Icons.Default.Edit,
                                        contentDescription = "Изменить",
                                        tint = fg.copy(alpha = 0.45f),
                                        modifier = Modifier.size(16.dp),
                                    )
                                }
                                TvIconButton(
                                    onClick = { persistSites(siteRules.filterNot { it == rule }) },
                                    enabled = !siteBusy,
                                    modifier = Modifier.size(32.dp),
                                ) {
                                    Icon(
                                        Icons.Default.Close,
                                        contentDescription = "Удалить",
                                        tint = fg.copy(alpha = 0.45f),
                                        modifier = Modifier.size(16.dp),
                                    )
                                }
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
                SearchFieldWithClear(
                    value = search,
                    onValueChange = { search = it },
                    placeholder = "Поиск...",
                    palette = palette,
                    fieldColors = fieldColors,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                )
                if (loading) {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = fg)
                    }
                } else {
                    LazyColumn(
                        state = appsListState,
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

@Composable
private fun SearchFieldWithClear(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    palette: ThemePalette,
    fieldColors: androidx.compose.material3.TextFieldColors,
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier,
        placeholder = {
            Text(placeholder, fontSize = 13.sp, color = palette.fieldPlaceholder)
        },
        singleLine = true,
        shape = RoundedCornerShape(12.dp),
        colors = fieldColors,
        trailingIcon = {
            if (value.isNotBlank()) {
                IconButton(onClick = { onValueChange("") }) {
                    Icon(
                        Icons.Filled.Close,
                        contentDescription = "Очистить поиск",
                        tint = palette.fg.copy(alpha = 0.55f),
                        modifier = Modifier.size(18.dp),
                    )
                }
            }
        },
    )
}
