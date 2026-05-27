package com.silent.vpn.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.DeviceInfo
import com.silent.vpn.data.UserProfile
import com.silent.vpn.ui.theme.parseColor

enum class VpnState { DISCONNECTED, CONNECTING, CONNECTED, DISCONNECTING }

private enum class MenuPage { ROOT, SUBSCRIPTION, EXCEPTIONS, HASHES, PROMO, DEVICES, SUPPORT, ABOUT }

private fun deviceTypeLabel(type: String): String = when (type.lowercase()) {
    "android" -> "Android"
    "pc", "windows" -> "ПК"
    "ios" -> "iOS"
    else -> type.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
}

private fun defaultDeviceName(type: String): String = when (type.lowercase()) {
    "android" -> "Android"
    "pc", "windows" -> "PC"
    "ios" -> "iOS"
    else -> deviceTypeLabel(type)
}

private fun sessionCustomLabel(d: DeviceInfo): String? {
    val defaults = setOf("Android", "ПК", "PC", "iOS", "Windows")
    if (d.device_name in defaults || d.device_name.startsWith("Bootstrap-", ignoreCase = true)) return null
    return d.device_name
}

@Composable
fun MainScreen(
    profile: UserProfile?,
    vpnState: VpnState,
    theme: ThemeData?,
    repo: com.silent.vpn.data.SilentRepository,
    sessionDeviceId: String? = null,
    vpnError: String?,
    onToggle: () -> Unit,
    onLogout: () -> Unit,
    onClearVpnError: () -> Unit,
    onCheckPromo: (String, (String) -> Unit) -> Unit,
    onInitPayment: (String, (String) -> Unit, (String) -> Unit) -> Unit,
    onOpenUrl: (String) -> Unit,
    onShowError: (String) -> Unit,
    onRenameDevice: (deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) -> Unit,
) {
    val bg = parseColor(theme?.background_color ?: "#FFFFFF", Color.White)
    val fg = parseColor(theme?.text_color ?: "#000000", Color.Black)
    val toggleOn = parseColor(theme?.toggle_on_color ?: "#000000", Color.Black)
    val toggleOff = parseColor(theme?.toggle_off_color ?: "#CCCCCC", Color(0xFFCCCCCC))

    var menuOpen by remember { mutableStateOf(false) }
    var menuPage by remember { mutableStateOf(MenuPage.ROOT) }
    var promoCode by remember { mutableStateOf("") }
    var promoMsg by remember { mutableStateOf("") }
    var showDebugLog by remember { mutableStateOf(false) }

    val isConnected = vpnState == VpnState.CONNECTED
    val isTransitioning = vpnState == VpnState.CONNECTING || vpnState == VpnState.DISCONNECTING

    val snackbarHostState = remember { SnackbarHostState() }
    LaunchedEffect(vpnError) {
        vpnError?.let {
            snackbarHostState.showSnackbar(it)
            onClearVpnError()
        }
    }

    val pulseAnim = rememberInfiniteTransition(label = "pulse")
    val pulseScale by pulseAnim.animateFloat(
        initialValue = 1f, targetValue = if (isConnected) 1.12f else 1f,
        animationSpec = infiniteRepeatable(tween(1500, easing = EaseInOut), RepeatMode.Reverse),
        label = "scale",
    )
    val toggleOffset by animateFloatAsState(
        targetValue = if (isConnected) 1f else 0f,
        animationSpec = spring(dampingRatio = 0.7f, stiffness = Spring.StiffnessMediumLow),
        label = "toggle",
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            // Title bar — название по центру, меню слева, лог справа
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(36.dp)
                    .border(0.5.dp, Color(0xFFF3F4F6))
                    .padding(horizontal = 4.dp),
                contentAlignment = Alignment.Center,
            ) {
                IconButton(
                    onClick = { menuOpen = true; menuPage = MenuPage.ROOT },
                    modifier = Modifier.align(Alignment.CenterStart).size(28.dp),
                ) {
                    Icon(Icons.Default.Menu, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
                }
                Text(
                    (theme?.app_name ?: "Silent").uppercase(),
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 3.sp,
                    fontSize = 12.sp,
                    color = fg,
                )
                DebugLogButton(
                    onClick = { showDebugLog = true },
                    modifier = Modifier.align(Alignment.CenterEnd),
                )
            }

            // Main content
            Box(modifier = Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        when (vpnState) {
                            VpnState.CONNECTED -> "Подключено"
                            VpnState.CONNECTING -> "Подключение..."
                            VpnState.DISCONNECTING -> "Отключение..."
                            VpnState.DISCONNECTED -> "Отключено"
                        },
                        color = when (vpnState) {
                            VpnState.CONNECTED -> Color(0xFF16A34A)
                            VpnState.DISCONNECTED -> fg.copy(alpha = 0.4f)
                            else -> fg.copy(alpha = 0.6f)
                        },
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        letterSpacing = 1.5.sp,
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Toggle 120x60 — как на PC
                    Box(contentAlignment = Alignment.Center, modifier = Modifier.size(120.dp, 60.dp)) {
                        if (isConnected) {
                            Box(
                                modifier = Modifier
                                    .fillMaxSize()
                                    .scale(pulseScale)
                                    .background(toggleOn.copy(alpha = 0.2f), CircleShape),
                            )
                        }
                        Box(
                            modifier = Modifier
                                .fillMaxSize()
                                .background(if (isConnected) toggleOn else toggleOff, CircleShape)
                                .clickable(enabled = !isTransitioning, onClick = onToggle),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            Box(
                                modifier = Modifier
                                    .padding(start = 4.dp)
                                    .offset(x = (120.dp - 48.dp - 8.dp) * toggleOffset)
                                    .size(48.dp)
                                    .background(bg, CircleShape)
                                    .border(2.dp, if (isConnected) toggleOn else toggleOff, CircleShape),
                            )
                        }
                    }

                    if (isTransitioning) {
                        Spacer(modifier = Modifier.height(16.dp))
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp, color = fg)
                    }
                }
            }

            // Bottom subscription — как на PC
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .border(0.5.dp, Color(0xFFF3F4F6))
                    .padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                when {
                    profile?.is_admin == true || profile?.subscription?.plan_type == "unlimited" -> {
                        Text("Бессрочно", color = Color(0xFF16A34A), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text("Полный доступ", color = fg.copy(alpha = 0.4f), fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                    profile?.subscription?.is_active == true && profile.subscription.plan_type == "trial" -> {
                        Text("Пробный период", color = Color(0xFF2563EB), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text(
                            "осталось ${profile.subscription.days_left} дн.",
                            color = fg.copy(alpha = 0.4f), fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                    profile?.subscription?.is_active == true -> {
                        Text("Оплачено", color = Color(0xFF16A34A), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text(
                            "до ${profile.subscription.expires_at?.take(10)?.split("-")?.reversed()?.joinToString(".")}",
                            color = fg.copy(alpha = 0.4f), fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                    else -> {
                        Button(
                            onClick = { menuOpen = true; menuPage = MenuPage.SUBSCRIPTION },
                            colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = bg),
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.fillMaxWidth().height(36.dp),
                        ) {
                            Text("Оформить подписку", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
            }
        }

        // Side drawer overlay — как на PC
        if (menuOpen) {
            Row(modifier = Modifier.fillMaxSize()) {
                Column(
                    modifier = Modifier
                        .width(208.dp)
                        .fillMaxHeight()
                        .background(bg)
                        .border(0.5.dp, Color(0xFFE5E7EB)),
                ) {
                    // Header
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(16.dp).border(0.5.dp, Color(0xFFF3F4F6)),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text(profile?.email ?: "—", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg, maxLines = 1)
                            Text("Аккаунт: ${profile?.display_id ?: "—"}", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.padding(top = 2.dp))
                            sessionDeviceId?.takeIf { it.isNotBlank() }?.let { sid ->
                                Text(
                                    "Сессия: ${sid.take(8).uppercase()}",
                                    fontSize = 11.sp,
                                    color = fg.copy(alpha = 0.35f),
                                    modifier = Modifier.padding(top = 2.dp),
                                )
                            }
                        }
                        IconButton(onClick = { menuOpen = false; menuPage = MenuPage.ROOT }, modifier = Modifier.size(24.dp)) {
                            Icon(Icons.Default.Close, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
                        }
                    }

                    when (menuPage) {
                        MenuPage.ROOT -> {
                            val items = listOf(
                                MenuPage.SUBSCRIPTION to "Подписка",
                                MenuPage.EXCEPTIONS to "Исключения приложений",
                                MenuPage.HASHES to "Хеши",
                                MenuPage.PROMO to "Промокод",
                                MenuPage.DEVICES to "Сессии (${profile?.devices_count ?: 0}/${profile?.max_devices ?: 3})",
                                MenuPage.SUPPORT to "Поддержка",
                                MenuPage.ABOUT to "О сервисе",
                            )
                            items.forEach { (page, label) ->
                                Row(
                                    modifier = Modifier.fillMaxWidth().clickable { menuPage = page }.padding(horizontal = 12.dp, vertical = 10.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(label, fontSize = 14.sp, color = fg, modifier = Modifier.weight(1f))
                                    Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = fg.copy(alpha = 0.3f), modifier = Modifier.size(14.dp))
                                }
                            }
                            TextButton(
                                onClick = { menuOpen = false; onLogout() },
                                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                            ) { Text("Выйти", color = Color(0xFFEF4444), fontSize = 14.sp) }
                        }
                        MenuPage.SUBSCRIPTION -> MenuSubscription(profile, fg, onBack = { menuPage = MenuPage.ROOT }, onInitPayment, onOpenUrl, onShowError)
                        MenuPage.EXCEPTIONS -> AppExclusionsScreen(repo, fg, bg) { menuPage = MenuPage.ROOT }
                        MenuPage.HASHES -> MenuHashesScreen(repo, fg) { menuPage = MenuPage.ROOT }
                        MenuPage.PROMO -> MenuPromo(fg, bg, promoCode, { promoCode = it }, promoMsg, { onCheckPromo(promoCode) { promoMsg = it } }) { menuPage = MenuPage.ROOT }
                        MenuPage.DEVICES -> MenuDevices(profile, fg, sessionDeviceId, vpnState, onRenameDevice) { menuPage = MenuPage.ROOT }
                        MenuPage.SUPPORT -> MenuSimplePage("Поддержка", "По вопросам обратитесь через email или Telegram.", fg) { menuPage = MenuPage.ROOT }
                        MenuPage.ABOUT -> MenuSimplePage("Silent VPN", "Версия 1.0.15\nWireGuard-туннель через VK TURN/DTLS", fg) { menuPage = MenuPage.ROOT }
                    }
                }
                Box(
                    modifier = Modifier.weight(1f).fillMaxHeight().background(Color.Black.copy(alpha = 0.2f))
                        .clickable { menuOpen = false; menuPage = MenuPage.ROOT },
                )
            }
        }

        SnackbarHost(snackbarHostState, modifier = Modifier.align(Alignment.BottomCenter))
        DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
    }
}

@Composable
private fun MenuSimplePage(title: String, body: String, fg: Color, onBack: () -> Unit) {
    Column(modifier = Modifier.padding(16.dp)) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        Text(body, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
private fun MenuSubscription(profile: UserProfile?, fg: Color, onBack: () -> Unit, onInitPayment: (String, (String) -> Unit, (String) -> Unit) -> Unit, onOpenUrl: (String) -> Unit, onShowError: (String) -> Unit) {
    Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        if (profile?.subscription?.is_active == true) {
            val planLabel = when (profile.subscription.plan_type) {
                "trial" -> "Пробный период"
                "monthly" -> "Месяц"
                "quarterly" -> "3 месяца"
                "yearly" -> "Год"
                else -> profile.subscription.plan_type ?: "—"
            }
            Text("Подписка активна", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
            Text("Тариф: $planLabel\nОсталось: ${profile.subscription.days_left} дней", fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp))
        } else {
            Text("Выберите тариф", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
            listOf("monthly" to ("Месяц" to "199 ₽"), "quarterly" to ("3 месяца" to "499 ₽"), "yearly" to ("Год" to "1 499 ₽")).forEach { (id, labelPrice) ->
                Button(
                    onClick = { onInitPayment(id, onOpenUrl, onShowError) },
                    colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = Color.White),
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                ) {
                    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text(labelPrice.first, fontSize = 12.sp)
                        Text(labelPrice.second, fontSize = 12.sp)
                    }
                }
            }
        }
    }
}

@Composable
private fun MenuPromo(fg: Color, bg: Color, promoCode: String, onPromoChange: (String) -> Unit, promoMsg: String, onApply: () -> Unit, onBack: () -> Unit) {
    Column(modifier = Modifier.padding(16.dp)) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text("Промокод", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        OutlinedTextField(value = promoCode, onValueChange = onPromoChange, placeholder = { Text("Введите код") }, modifier = Modifier.fillMaxWidth().padding(top = 12.dp), shape = RoundedCornerShape(12.dp))
        Button(onClick = onApply, colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = bg), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
            Text("Применить", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
        if (promoMsg.isNotBlank()) Text(promoMsg, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp).fillMaxWidth(), textAlign = TextAlign.Center)
    }
}

@Composable
private fun MenuDevices(
    profile: UserProfile?,
    fg: Color,
    sessionDeviceId: String?,
    vpnState: VpnState,
    onRenameDevice: (deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) -> Unit,
    onBack: () -> Unit,
) {
    var renameTarget by remember { mutableStateOf<DeviceInfo?>(null) }
    var renameText by remember { mutableStateOf("") }
    var renameSaving by remember { mutableStateOf(false) }

    if (renameTarget != null) {
        AlertDialog(
            onDismissRequest = { if (!renameSaving) renameTarget = null },
            title = { Text("Приписать имя", fontSize = 14.sp) },
            text = {
                OutlinedTextField(
                    value = renameText,
                    onValueChange = { renameText = it.take(64) },
                    placeholder = { Text("Например: Мой телефон") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = {
                TextButton(
                    enabled = !renameSaving,
                    onClick = {
                        val target = renameTarget ?: return@TextButton
                        renameSaving = true
                        val name = renameText.trim().ifBlank { defaultDeviceName(target.device_type) }
                        onRenameDevice(target.id, name) { ok, _ ->
                            renameSaving = false
                            if (ok) renameTarget = null
                        }
                    },
                ) { Text("Сохранить") }
            },
            dismissButton = {
                TextButton(onClick = { if (!renameSaving) renameTarget = null }) {
                    Text("Отмена")
                }
            },
        )
    }

    Column(modifier = Modifier.padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text("Сессии", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        val localOnline = vpnState == VpnState.CONNECTED || vpnState == VpnState.CONNECTING
        val onlineCount = profile?.devices?.count { d ->
            d.is_connected || (localOnline && d.id == sessionDeviceId)
        } ?: 0
        Text(
            "VPN онлайн: $onlineCount из ${profile?.devices_count ?: 0}",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.45f),
            modifier = Modifier.padding(bottom = 8.dp),
        )
        profile?.devices?.forEach { d ->
            val online = d.is_connected || (localOnline && d.id == sessionDeviceId)
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 8.dp)
                    .border(0.5.dp, Color(0xFFF3F4F6))
                    .padding(horizontal = 8.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier.size(10.dp).background(
                        if (online) Color(0xFF22C55E) else Color(0xFFD1D5DB),
                        CircleShape,
                    ),
                )
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .padding(start = 10.dp),
                ) {
                    Text(
                        deviceTypeLabel(d.device_type),
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Medium,
                        color = fg,
                    )
                    sessionCustomLabel(d)?.let { label ->
                        Text(
                            label,
                            fontSize = 11.sp,
                            color = fg.copy(alpha = 0.45f),
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
                IconButton(
                    onClick = {
                        renameTarget = d
                        renameText = sessionCustomLabel(d).orEmpty()
                    },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Default.Edit, contentDescription = "Подписать", tint = fg.copy(alpha = 0.45f), modifier = Modifier.size(16.dp))
                }
            }
        }
    }
}
