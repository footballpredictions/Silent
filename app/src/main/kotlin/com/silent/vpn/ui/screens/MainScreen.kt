package com.silent.vpn.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import android.graphics.Matrix
import android.graphics.Paint as AndroidPaint
import android.graphics.SweepGradient
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import androidx.compose.ui.zIndex
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.BuildConfig
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog
import com.silent.vpn.ui.components.MenuNavItem
import com.silent.vpn.ui.components.MenuNavLogout
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.DeviceInfo
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.UpdateCheckResponse
import com.silent.vpn.ui.theme.parseColor
import com.silent.vpn.ui.theme.UiColors
import com.silent.vpn.ui.theme.UiDimens
import com.silent.vpn.ui.theme.UiFont
import com.silent.vpn.ui.theme.displayAppName
import com.silent.vpn.ui.theme.mutedFg

private const val THUMB_SIZE_DP = 48f
private const val TRACK_WIDTH_DP = 120f
private const val TRACK_HEIGHT_DP = 60f
private const val THUMB_PULSE_PEAK = 1.10f
private const val THUMB_PULSE_MS = 520
private const val SNAKE_STROKE_DP = 4f
private const val SNAKE_ROTATION_MS = 2200
private const val SNAKE_TAIL_START = 0.020f
private const val SNAKE_HEAD_POS = 0.875f

/** Стопы по часовой от кончика хвоста к голове — без обхода через зазор (иначе полосы). */
private fun buildSnakeGradientArrays(snakeColor: Color): Pair<IntArray, FloatArray> {
    val colors = mutableListOf<Int>()
    val positions = mutableListOf<Float>()
    val transparent = Color.Transparent.toArgb()
    val span = SNAKE_HEAD_POS - SNAKE_TAIL_START
    val steps = 96

    positions.add(0f)
    colors.add(transparent)
    positions.add(SNAKE_TAIL_START - 0.002f)
    colors.add(transparent)

    for (i in 0..steps) {
        val t = i / steps.toFloat()
        val pos = SNAKE_TAIL_START + span * t
        val alpha = t.pow(4.4f) * 0.98f
        positions.add(pos)
        colors.add(snakeColor.copy(alpha = alpha).toArgb())
    }

    var gap = SNAKE_HEAD_POS + 0.003f
    while (gap <= 1f) {
        positions.add(gap)
        colors.add(transparent)
        gap += 0.02f
    }
    positions.add(1f)
    colors.add(transparent)

    return colors.toIntArray() to positions.toFloatArray()
}

private fun DrawScope.drawToggleSnakeRing(
    snakeColor: Color,
    rotationDeg: Float,
    strokePx: Float,
) {
    val center = Offset(size.width / 2f, size.height / 2f)
    val radius = (size.minDimension - strokePx) / 2f
    val (colors, positions) = buildSnakeGradientArrays(snakeColor)
    drawIntoCanvas { canvas ->
        val shader = SweepGradient(center.x, center.y, colors, positions).apply {
            val matrix = Matrix()
            matrix.setRotate(rotationDeg - 90f, center.x, center.y)
            setLocalMatrix(matrix)
        }
        val paint = AndroidPaint().apply {
            isAntiAlias = true
            isDither = true
            style = AndroidPaint.Style.STROKE
            strokeWidth = strokePx
            strokeCap = AndroidPaint.Cap.ROUND
            this.shader = shader
        }
        canvas.nativeCanvas.drawCircle(center.x, center.y, radius, paint)
    }
    val headAngleRad = Math.toRadians(
        (rotationDeg - 90f + SNAKE_HEAD_POS * 360f).toDouble(),
    )
    val capCenter = Offset(
        center.x + radius * cos(headAngleRad).toFloat(),
        center.y + radius * sin(headAngleRad).toFloat(),
    )
    drawCircle(
        color = snakeColor,
        radius = strokePx / 2f,
        center = capCenter,
    )
}

@Composable
private fun VpnToggleThumb(
    active: Boolean,
    isConnected: Boolean,
    travelX: Dp,
    bg: Color,
    toggleOn: Color,
    toggleOff: Color,
    snakeColor: Color,
) {
    val scaleAnim = remember { Animatable(1f) }
    LaunchedEffect(active) {
        if (!active) {
            scaleAnim.snapTo(1f)
            return@LaunchedEffect
        }
        while (true) {
            scaleAnim.animateTo(THUMB_PULSE_PEAK, tween(THUMB_PULSE_MS, easing = FastOutSlowInEasing))
            scaleAnim.animateTo(1f, tween(THUMB_PULSE_MS, easing = FastOutSlowInEasing))
        }
    }
    val scale by scaleAnim.asState()
    val showBorder = !active || isConnected
    val showSnake = active && !isConnected
    val borderColor = if (isConnected) toggleOn else toggleOff
    val snakeSpin = rememberInfiniteTransition(label = "thumbSnake")
    val snakeRotation by snakeSpin.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(SNAKE_ROTATION_MS, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "snakeRot",
    )
    val density = LocalDensity.current
    Box(
        modifier = Modifier
            .padding(start = 4.dp)
            .offset(x = travelX)
            .size(THUMB_SIZE_DP.dp)
            .zIndex(1f)
            .graphicsLayer {
                scaleX = scale
                scaleY = scale
                clip = false
            },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(bg, CircleShape)
                .then(
                    if (showBorder) Modifier.border(2.dp, borderColor, CircleShape) else Modifier,
                ),
        )
        if (showSnake) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val strokePx = with(density) { SNAKE_STROKE_DP.dp.toPx() }
                drawToggleSnakeRing(
                    snakeColor = snakeColor,
                    rotationDeg = snakeRotation,
                    strokePx = strokePx,
                )
            }
        }
    }
}

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
    onDevicesScreenActive: (Boolean) -> Unit = {},
    onVpnProfilePolling: (Boolean) -> Unit = {},
    updateInfo: UpdateCheckResponse? = null,
    updateDownloading: Boolean = false,
    updateProgress: Int = 0,
    onUpdateClick: () -> Unit = {},
    onUpdatePolling: (Boolean) -> Unit = {},
) {
    val bg = parseColor(theme?.background_color ?: "#FFFFFF", Color.White)
    val fg = parseColor(theme?.text_color ?: "#000000", Color.Black)
    val toggleOn = parseColor(theme?.toggle_on_color ?: "#000000", Color.Black)
    val toggleOff = parseColor(theme?.toggle_off_color ?: "#CCCCCC", Color(0xFFCCCCCC))
    val updateBarBg = parseColor(theme?.update_bar_background_color ?: "#2563EB", Color(0xFF2563EB))
    val updateBarFg = parseColor(theme?.update_bar_text_color ?: "#FFFFFF", Color.White)
    val updateBarProgress = parseColor(theme?.update_bar_progress_color ?: "#1D4ED8", Color(0xFF1D4ED8))
    val updateLabelAvailable = theme?.update_bar_label_available?.takeIf { it.isNotBlank() } ?: "Доступно обновление"
    val updateLabelDownloading = theme?.update_bar_label_downloading?.takeIf { it.isNotBlank() } ?: "Скачивание…"

    var menuOpen by remember { mutableStateOf(false) }
    var menuPage by remember { mutableStateOf(MenuPage.ROOT) }
    var promoCode by remember { mutableStateOf("") }
    var promoMsg by remember { mutableStateOf("") }
    var showDebugLog by remember { mutableStateOf(false) }

    LaunchedEffect(menuOpen, menuPage) {
        onDevicesScreenActive(menuOpen && menuPage == MenuPage.DEVICES)
    }
    LaunchedEffect(vpnState, menuOpen, menuPage) {
        val onSessions = menuOpen && menuPage == MenuPage.DEVICES
        onVpnProfilePolling(
            vpnState == VpnState.CONNECTED ||
                vpnState == VpnState.CONNECTING ||
                onSessions,
        )
    }
    LaunchedEffect(Unit) {
        onUpdatePolling(true)
    }
    DisposableEffect(Unit) {
        onDispose {
            onDevicesScreenActive(false)
            onVpnProfilePolling(false)
            onUpdatePolling(false)
        }
    }

    val isConnected = vpnState == VpnState.CONNECTED
    val isTransitioning = vpnState == VpnState.CONNECTING || vpnState == VpnState.DISCONNECTING
    var toggleBusy by remember { mutableStateOf(false) }
    LaunchedEffect(vpnState) {
        when (vpnState) {
            VpnState.CONNECTED, VpnState.DISCONNECTED -> toggleBusy = false
            else -> Unit
        }
    }
    val thumbActive = isTransitioning || toggleBusy

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
    val toggleInteraction = remember { MutableInteractionSource() }
    val togglePressed by toggleInteraction.collectIsPressedAsState()
    val togglePressScale by animateFloatAsState(
        targetValue = if (togglePressed && !thumbActive) 0.95f else 1f,
        animationSpec = spring(dampingRatio = 0.6f, stiffness = Spring.StiffnessMedium),
        label = "togglePress",
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bg)
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            val density = LocalDensity.current
            // Title bar — название по центру, меню слева, лог справа
            val titleBarDivider = Modifier.drawBehind {
                val stroke = with(density) { UiDimens.borderThin.toPx() }
                drawLine(
                    color = UiColors.Gray100,
                    start = Offset(0f, size.height - (stroke / 2f)),
                    end = Offset(size.width, size.height - (stroke / 2f)),
                    strokeWidth = stroke,
                )
            }
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(UiDimens.titleBarHeight)
                    .then(titleBarDivider)
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
                    displayAppName(theme),
                    fontWeight = FontWeight.Bold,
                    letterSpacing = UiFont.titleTracking,
                    fontSize = UiFont.xs,
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

                    // Toggle 120x60 — как на PC (active:scale-95)
                    val thumbTravel = (TRACK_WIDTH_DP - THUMB_SIZE_DP - 8f).dp
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .padding(vertical = 14.dp)
                            .size(TRACK_WIDTH_DP.dp, TRACK_HEIGHT_DP.dp + 28.dp),
                    ) {
                        Box(
                            contentAlignment = Alignment.CenterStart,
                            modifier = Modifier
                                .size(TRACK_WIDTH_DP.dp, TRACK_HEIGHT_DP.dp)
                                .scale(togglePressScale)
                                .clickable(
                                    enabled = !thumbActive,
                                    interactionSource = toggleInteraction,
                                    indication = null,
                                    onClick = {
                                        toggleBusy = true
                                        onToggle()
                                    },
                                ),
                        ) {
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
                                    .background(if (isConnected) toggleOn else toggleOff, CircleShape),
                            )
                            VpnToggleThumb(
                                active = thumbActive,
                                isConnected = isConnected,
                                travelX = thumbTravel * toggleOffset,
                                bg = bg,
                                toggleOn = toggleOn,
                                toggleOff = toggleOff,
                                snakeColor = fg,
                            )
                        }
                    }
                }
            }

            // Bottom subscription — как на PC
            val bottomDivider = Modifier.drawBehind {
                val stroke = with(density) { UiDimens.borderThin.toPx() }
                drawLine(
                    color = UiColors.Gray100,
                    start = Offset(0f, stroke / 2f),
                    end = Offset(size.width, stroke / 2f),
                    strokeWidth = stroke,
                )
            }
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .then(bottomDivider)
                    .padding(UiDimens.pagePadding),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                when {
                    updateInfo?.available == true -> {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(36.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .background(updateBarBg)
                                .clickable(enabled = !updateDownloading, onClick = onUpdateClick),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (updateDownloading) {
                                Box(
                                    modifier = Modifier
                                        .align(Alignment.CenterStart)
                                        .fillMaxHeight()
                                        .fillMaxWidth(updateProgress.coerceIn(0, 100) / 100f)
                                        .background(updateBarProgress.copy(alpha = 0.35f)),
                                )
                            }
                            Text(
                                if (updateDownloading) "$updateLabelDownloading $updateProgress%"
                                else "$updateLabelAvailable v${updateInfo.version}",
                                fontSize = 12.sp,
                                fontWeight = FontWeight.SemiBold,
                                color = updateBarFg,
                            )
                        }
                    }
                    profile == null -> {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            strokeWidth = 2.dp,
                            color = fg.copy(alpha = 0.5f),
                        )
                    }
                    profile?.subscription?.plan_type == "test" -> {
                        Text("Тестовый режим", color = Color(0xFF9333EA), fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text("Безлимит", color = fg.copy(alpha = 0.4f), fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp))
                    }
                    profile.is_admin || profile.subscription?.plan_type == "unlimited" -> {
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

        // Side drawer (половина) — только список; пункты меню на полный экран
        if (menuOpen) {
            if (menuPage == MenuPage.ROOT) {
                Row(modifier = Modifier.fillMaxSize()) {
                    Column(
                        modifier = Modifier
                            .width(UiDimens.menuWidth)
                            .fillMaxHeight()
                            .background(bg)
                            .border(UiDimens.borderThin, UiColors.Gray200),
                    ) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(UiDimens.pagePadding),
                            verticalAlignment = Alignment.Top,
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    profile?.email ?: "—",
                                    fontSize = UiFont.xs,
                                    fontWeight = FontWeight.SemiBold,
                                    color = fg,
                                    maxLines = 1,
                                )
                                Text(
                                    "Аккаунт: ${profile?.display_id ?: "—"}",
                                    fontSize = UiFont.xs,
                                    color = mutedFg(fg),
                                    modifier = Modifier.padding(top = 2.dp),
                                )
                                sessionDeviceId?.takeIf { it.isNotBlank() }?.let { sid ->
                                    Text(
                                        "Сессия: ${sid.take(8).uppercase()}",
                                        fontSize = UiFont.caption,
                                        color = mutedFg(fg, 0.35f),
                                        modifier = Modifier.padding(top = 2.dp),
                                    )
                                }
                            }
                            IconButton(
                                onClick = { menuOpen = false; menuPage = MenuPage.ROOT },
                                modifier = Modifier.size(24.dp),
                            ) {
                                Icon(Icons.Default.Close, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
                            }
                        }
                        HorizontalDivider(color = UiColors.Gray100, thickness = UiDimens.borderThin)
                        Column(modifier = Modifier.padding(UiDimens.menuNavPadding)) {
                            val items = buildList {
                                add(MenuPage.SUBSCRIPTION to "Подписка")
                                add(MenuPage.EXCEPTIONS to "Исключения приложений")
                                if (BuildConfig.DEBUG) add(MenuPage.HASHES to "Хеши")
                                add(MenuPage.PROMO to "Промокод")
                                add(MenuPage.DEVICES to "Сессии (${profile?.devices_count ?: 0}/${profile?.max_devices ?: 3})")
                                add(MenuPage.SUPPORT to "Поддержка")
                                add(MenuPage.ABOUT to "О сервисе")
                            }
                            items.forEach { (page, label) ->
                                MenuNavItem(label = label, fg = fg, onClick = { menuPage = page })
                            }
                            MenuNavLogout(onClick = { menuOpen = false; onLogout() })
                        }
                    }
                    Box(
                        modifier = Modifier.weight(1f).fillMaxHeight().background(Color.Black.copy(alpha = 0.2f))
                            .clickable { menuOpen = false; menuPage = MenuPage.ROOT },
                    )
                }
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .background(bg),
                ) {
                    when (menuPage) {
                        MenuPage.SUBSCRIPTION -> MenuSubscription(
                            profile = profile,
                            fg = fg,
                            onBack = { menuPage = MenuPage.ROOT },
                            onInitPayment = onInitPayment,
                            onOpenUrl = onOpenUrl,
                            onShowError = onShowError,
                        )
                        MenuPage.EXCEPTIONS -> AppExclusionsScreen(repo, fg, bg) { menuPage = MenuPage.ROOT }
                        MenuPage.HASHES -> MenuHashesScreen(repo, fg) { menuPage = MenuPage.ROOT }
                        MenuPage.PROMO -> MenuPromo(fg, bg, promoCode, { promoCode = it }, promoMsg, { onCheckPromo(promoCode) { promoMsg = it } }) { menuPage = MenuPage.ROOT }
                        MenuPage.DEVICES -> MenuDevices(profile, fg, sessionDeviceId, vpnState, onRenameDevice) { menuPage = MenuPage.ROOT }
                        MenuPage.SUPPORT -> MenuSimplePage("Поддержка", "По вопросам обратитесь через email или Telegram.", fg) { menuPage = MenuPage.ROOT }
                        MenuPage.ABOUT -> MenuSimplePage("Silent VPN", "Версия ${com.silent.vpn.BuildConfig.VERSION_NAME}\nWireGuard-туннель через VK TURN/DTLS", fg) { menuPage = MenuPage.ROOT }
                        else -> Unit
                    }
                }
            }
        }

        SnackbarHost(snackbarHostState, modifier = Modifier.align(Alignment.BottomCenter))
        DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
    }
}

@Composable
private fun MenuSimplePage(title: String, body: String, fg: Color, onBack: () -> Unit) {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        Text(body, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
private fun MenuSubscription(
    profile: UserProfile?,
    fg: Color,
    onBack: () -> Unit,
    onInitPayment: (String, (String) -> Unit, (String) -> Unit) -> Unit,
    onOpenUrl: (String) -> Unit,
    onShowError: (String) -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text(
            "Подписка и оплата обновляются автоматически при включённом VPN.",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.45f),
            modifier = Modifier.padding(bottom = 12.dp),
        )
        if (profile?.subscription?.is_active == true) {
            val planType = profile.subscription.plan_type
            val planLabel = when (planType) {
                "trial" -> "Пробный период"
                "test" -> "Тестовый режим"
                "monthly" -> "Месяц"
                "quarterly" -> "3 месяца"
                "yearly" -> "Год"
                "unlimited" -> "Бессрочно"
                else -> planType ?: "—"
            }
            val unlimitedLike = profile.is_admin || planType == "unlimited" || planType == "test"
            Text("Подписка активна", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
            Text(
                if (unlimitedLike) "Тариф: $planLabel\nБезлимитный доступ"
                else "Тариф: $planLabel\nОсталось: ${profile.subscription.days_left} дней",
                fontSize = 12.sp,
                color = fg.copy(alpha = 0.5f),
                modifier = Modifier.padding(top = 8.dp),
            )
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
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
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

    Column(modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f), modifier = Modifier.clickable(onClick = onBack).padding(bottom = 16.dp))
        Text("Сессии", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        val maxSlots = profile?.max_devices ?: 3
        val slotsUsed = profile?.devices_count ?: profile?.devices?.size ?: 0
        val localOnline = vpnState == VpnState.CONNECTED || vpnState == VpnState.CONNECTING
        fun deviceOnline(d: DeviceInfo): Boolean {
            if (d.is_connected) return true
            val isSelf = !sessionDeviceId.isNullOrBlank() && d.id == sessionDeviceId
            // Только своё устройство — optimistic; остальные строго с сервера
            return localOnline && isSelf
        }
        val devices = profile?.devices.orEmpty()
        val listOnline = devices.count { deviceOnline(it) }
        val serverOnline = profile?.connected_count ?: listOnline
        val onlineCount = serverOnline.coerceIn(0, maxSlots)
        Text(
            "VPN онлайн: $onlineCount из $maxSlots",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.45f),
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Занято слотов: $slotsUsed из $maxSlots",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.35f),
            modifier = Modifier.padding(bottom = 8.dp),
        )
        profile?.devices?.forEach { d ->
            val online = deviceOnline(d)
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
                    .padding(vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier.size(10.dp).background(
                        if (online) UiColors.Green500 else UiColors.Gray300,
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
