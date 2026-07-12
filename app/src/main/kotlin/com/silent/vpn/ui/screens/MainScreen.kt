package com.silent.vpn.ui.screens

import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.Canvas
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
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
import androidx.compose.ui.res.painterResource
import com.silent.vpn.BuildConfig
import com.silent.vpn.R
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog
import com.silent.vpn.ui.components.MenuNavItem
import com.silent.vpn.ui.components.MenuNavLogout
import com.silent.vpn.ui.components.ThemeModeToggle
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.DeviceInfo
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.deviceLimitLabel
import com.silent.vpn.data.sessionsBadge
import com.silent.vpn.data.UpdateCheckResponse
import com.silent.vpn.ui.theme.AppearanceMode
import com.silent.vpn.ui.theme.DarkSystemBarStrip
import com.silent.vpn.ui.theme.ThemePalette
import com.silent.vpn.ui.theme.needsNeonGlow
import com.silent.vpn.ui.theme.neonShadow
import com.silent.vpn.ui.theme.parseColor
import com.silent.vpn.ui.theme.resolveThemePalette
import com.silent.vpn.ui.theme.themeTextFieldColors
import com.silent.vpn.ui.theme.UiColors
import com.silent.vpn.ui.theme.UiDimens
import com.silent.vpn.ui.theme.UiFont
import com.silent.vpn.ui.theme.displayAppName
import com.silent.vpn.ui.theme.mutedFg
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.graphics.Shadow
import com.silent.vpn.ui.tv.TvIconButton
import com.silent.vpn.ui.tv.TvPrimaryButton
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.ui.tv.tvConsumeFocusUp
import com.silent.vpn.ui.tv.tvToggleClickable
import com.silent.vpn.util.rememberIsTv

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
private fun buildSnakeGradientArrays(snakeColor: Color, gapColor: Color): Pair<IntArray, FloatArray> {
    val colors = mutableListOf<Int>()
    val positions = mutableListOf<Float>()
    val gapArgb = gapColor.toArgb()
    val span = SNAKE_HEAD_POS - SNAKE_TAIL_START
    val steps = 96

    positions.add(0f)
    colors.add(gapArgb)
    positions.add(SNAKE_TAIL_START - 0.002f)
    colors.add(gapArgb)

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
        colors.add(gapArgb)
        gap += 0.02f
    }
    positions.add(1f)
    colors.add(gapArgb)

    return colors.toIntArray() to positions.toFloatArray()
}

private fun DrawScope.drawToggleSnakeRing(
    snakeColor: Color,
    thumbBg: Color,
    rotationDeg: Float,
    strokePx: Float,
) {
    val center = Offset(size.width / 2f, size.height / 2f)
    val radius = (size.minDimension - strokePx) / 2f
    val (colors, positions) = buildSnakeGradientArrays(snakeColor, thumbBg)
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
                .clip(CircleShape)
                .background(bg, CircleShape),
        )
        if (showBorder) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val borderPx = with(density) { 2.dp.toPx() }
                drawCircle(
                    color = borderColor,
                    radius = size.minDimension / 2f - borderPx / 2f,
                    style = Stroke(width = borderPx),
                )
            }
        }
        if (showSnake) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val strokePx = with(density) { SNAKE_STROKE_DP.dp.toPx() }
                drawToggleSnakeRing(
                    snakeColor = snakeColor,
                    thumbBg = bg,
                    rotationDeg = snakeRotation,
                    strokePx = strokePx,
                )
            }
        }
    }
}

enum class VpnState { DISCONNECTED, CONNECTING, CONNECTED, DISCONNECTING }

private enum class MenuPage { ROOT, SUBSCRIPTION, EXCEPTIONS, DNS, VK_CRED, HASHES, BONUSES, DEVICES, SUPPORT, ABOUT }

private fun deviceTypeLabel(type: String): String = when (type.lowercase()) {
    "android" -> "Android"
    "android_tv" -> "Android TV"
    "pc", "windows" -> "ПК"
    "ios" -> "iOS"
    else -> type.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
}

private fun defaultDeviceName(type: String): String = when (type.lowercase()) {
    "android" -> "Android"
    "android_tv" -> "Android TV"
    "pc", "windows" -> "PC"
    "ios" -> "iOS"
    else -> deviceTypeLabel(type)
}

private fun sessionCustomLabel(d: DeviceInfo): String? {
    val defaults = setOf("Android", "Android TV", "ПК", "PC", "iOS", "Windows")
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
    onLoadReferral: ((com.silent.vpn.data.ReferralInfo?) -> Unit) -> Unit = {},
    onInitPayment: (String, (String) -> Unit, (String) -> Unit) -> Unit,
    onOpenUrl: (String) -> Unit,
    onShowError: (String) -> Unit,
    onRenameDevice: (deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) -> Unit,
    onDeleteDevice: (deviceId: String, onResult: (Boolean, String?) -> Unit) -> Unit,
    onDevicesScreenActive: (Boolean) -> Unit = {},
    onVpnProfilePolling: (Boolean) -> Unit = {},
    updateInfo: UpdateCheckResponse? = null,
    updateDownloading: Boolean = false,
    updateProgress: Int = 0,
    onUpdateClick: () -> Unit = {},
    onUpdatePolling: (Boolean) -> Unit = {},
    appearanceMode: AppearanceMode = AppearanceMode.LIGHT,
    onToggleAppearance: () -> Unit = {},
    onRefreshTelegramChannel: () -> Unit = {},
) {
    val palette = remember(theme, appearanceMode) { theme.resolveThemePalette(appearanceMode) }
    val bg = palette.bg
    val fg = palette.fg
    val toggleOn = palette.toggleOn
    val toggleOff = palette.toggleOff
    val updateBarBg = palette.updateBarBg
    val updateBarFg = palette.updateBarFg
    val updateBarProgress = palette.updateBarProgress
    val updateLabelAvailable = theme?.update_bar_label_available?.takeIf { it.isNotBlank() } ?: "Доступно обновление"
    val updateLabelDownloading = theme?.update_bar_label_downloading?.takeIf { it.isNotBlank() } ?: "Скачивание…"
    val statusGreen = palette.green

    var menuOpen by remember { mutableStateOf(false) }
    var menuPage by remember { mutableStateOf(MenuPage.ROOT) }
    var promoCode by remember { mutableStateOf("") }
    var promoMsg by remember { mutableStateOf("") }
    var referralInfo by remember { mutableStateOf<com.silent.vpn.data.ReferralInfo?>(null) }
    var referralCopyMsg by remember { mutableStateOf("") }
    var showDebugLog by remember { mutableStateOf(false) }

    LaunchedEffect(menuOpen, menuPage) {
        onDevicesScreenActive(menuOpen && menuPage == MenuPage.DEVICES)
    }
    LaunchedEffect(vpnState, menuOpen, menuPage) {
        val onSessions = menuOpen && menuPage == MenuPage.DEVICES
        onVpnProfilePolling(vpnState == VpnState.CONNECTED || onSessions)
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

    val isTv = rememberIsTv()
    val toggleScale = if (isTv) 1.45f else 1f
    val blockMainFocus = isTv && menuOpen

    val isConnected = vpnState == VpnState.CONNECTED
    val isTransitioning = vpnState == VpnState.CONNECTING || vpnState == VpnState.DISCONNECTING
    val thumbActive = isTransitioning

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
            // Сначала серые полосы под status/nav (видны в зоне insets), затем контент на bg
            .background(if (palette.dark) DarkSystemBarStrip else bg)
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .background(bg),
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            val density = LocalDensity.current
            // Title bar — название по центру, меню слева, лог справа
            val titleBarDivider = Modifier.drawBehind {
                val stroke = with(density) { UiDimens.borderThin.toPx() }
                val lineColor = if (palette.dark) Color(0xFF3F3F46) else palette.border
                drawLine(
                    color = lineColor,
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
                TvIconButton(
                    onClick = { menuOpen = true; menuPage = MenuPage.ROOT },
                    modifier = Modifier.align(Alignment.CenterStart).size(28.dp),
                    enabled = !blockMainFocus,
                    requestFocusOnOpen = isTv && !menuOpen,
                    requestFocusKey = menuOpen,
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
                Row(
                    modifier = Modifier.align(Alignment.CenterEnd).padding(end = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    ThemeModeToggle(
                        mode = appearanceMode,
                        onToggle = onToggleAppearance,
                        color = fg,
                    )
                    if (BuildConfig.DEBUG) {
                        DebugLogButton(
                            onClick = { showDebugLog = true },
                            focusEnabled = !blockMainFocus,
                        )
                    }
                }
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
                            VpnState.CONNECTED -> statusGreen
                            VpnState.DISCONNECTED -> fg.copy(alpha = 0.4f)
                            else -> fg.copy(alpha = 0.6f)
                        },
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        letterSpacing = 1.5.sp,
                        style = TextStyle(
                            shadow = when {
                                vpnState == VpnState.CONNECTED && needsNeonGlow(statusGreen, palette.dark) ->
                                    neonShadow(statusGreen)
                                else -> null
                            },
                        ),
                    )

                    Spacer(modifier = Modifier.height(24.dp))

                    // Toggle 120x60 — как на PC (active:scale-95)
                    val thumbTravel = (TRACK_WIDTH_DP - THUMB_SIZE_DP - 8f).dp
                    val trackW = TRACK_WIDTH_DP.dp
                    val trackH = TRACK_HEIGHT_DP.dp
                    Box(
                        contentAlignment = Alignment.Center,
                        modifier = Modifier
                            .padding(vertical = 14.dp)
                            .size(trackW * toggleScale + 12.dp, trackH * toggleScale + 20.dp)
                            .then(
                                if (isTv) {
                                    Modifier.tvToggleClickable(
                                        enabled = !thumbActive && !blockMainFocus,
                                        onClick = onToggle,
                                    )
                                } else {
                                    Modifier
                                },
                            ),
                    ) {
                        Box(
                            contentAlignment = Alignment.CenterStart,
                            modifier = Modifier
                                .scale(toggleScale)
                                .size(trackW, trackH)
                                .scale(togglePressScale)
                                .then(
                                    if (!isTv) {
                                        Modifier.clickable(
                                            enabled = !thumbActive,
                                            interactionSource = toggleInteraction,
                                            indication = null,
                                            onClick = onToggle,
                                        )
                                    } else {
                                        Modifier
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
                    color = palette.border,
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
                        Text("Бессрочно", color = statusGreen, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
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
                        Text("Оплачено", color = statusGreen, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                        Text(
                            "до ${profile.subscription.expires_at?.take(10)?.split("-")?.reversed()?.joinToString(".")}",
                            color = fg.copy(alpha = 0.4f), fontSize = 12.sp, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                    else -> {
                        TvPrimaryButton(
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
                val drawerBg = palette.surface
                // Dark: тонкая/мягкая кромка (не #52525B — слишком выделялась)
                val drawerEdge = if (palette.dark) palette.border else palette.borderStrong
                Row(modifier = Modifier.fillMaxSize()) {
                    Column(
                        modifier = Modifier
                            .width(UiDimens.menuWidth)
                            .fillMaxHeight()
                            .background(drawerBg)
                            .border(
                                width = if (palette.dark) 0.5.dp else UiDimens.borderThin,
                                color = drawerEdge,
                            ),
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
                            TvIconButton(
                                onClick = { menuOpen = false; menuPage = MenuPage.ROOT },
                                modifier = Modifier.size(24.dp),
                                requestFocusOnOpen = isTv && menuOpen,
                                requestFocusKey = menuOpen,
                                blockFocusUp = isTv,
                            ) {
                                Icon(Icons.Default.Close, contentDescription = null, tint = fg, modifier = Modifier.size(16.dp))
                            }
                        }
                        HorizontalDivider(
                            color = if (palette.dark) Color(0xFF3F3F46) else palette.border,
                            thickness = UiDimens.borderThin,
                        )
                        val menuItems = buildList {
                            add(Triple(MenuPage.SUBSCRIPTION, "Подписка", null as String?))
                            add(Triple(MenuPage.EXCEPTIONS, "Исключения приложений", null))
                            if (BuildConfig.DEBUG) {
                                add(
                                    Triple(
                                        MenuPage.DNS,
                                        "DNS",
                                        repo.getDnsPreset().title,
                                    ),
                                )
                            }
                            if (BuildConfig.DEBUG) {
                                add(
                                    Triple(
                                        MenuPage.VK_CRED,
                                        "Режим VK-кредов",
                                        repo.vkCredStrategyLabel(),
                                    ),
                                )
                            }
                            if (BuildConfig.DEBUG) add(Triple(MenuPage.HASHES, "Хеши", null))
                            add(Triple(MenuPage.BONUSES, theme?.menu_bonuses_label?.takeIf { it.isNotBlank() } ?: "Бонусы", null))
                            add(Triple(MenuPage.DEVICES, "Сессии (${profile?.sessionsBadge() ?: "0/3"})", null))
                            add(Triple(MenuPage.SUPPORT, "Поддержка", null))
                            add(Triple(MenuPage.ABOUT, "О сервисе", null))
                        }
                        LazyColumn(
                            modifier = Modifier
                                .weight(1f)
                                .fillMaxWidth()
                                .padding(horizontal = UiDimens.menuNavPadding),
                            contentPadding = PaddingValues(bottom = 32.dp),
                        ) {
                            items(
                                items = menuItems,
                                key = { (page, _, _) -> page.name },
                            ) { (page, label, badge) ->
                                val text = if (badge != null) "$label  ·  $badge" else label
                                MenuNavItem(label = text, fg = fg, onClick = {
                                    menuPage = page
                                    if (page == MenuPage.BONUSES) {
                                        onLoadReferral { referralInfo = it }
                                    }
                                })
                            }
                            if (BuildConfig.DEBUG) {
                                val proxyUrl = theme?.telegram_proxy_url?.trim().orEmpty()
                                if (proxyUrl.isNotEmpty()) {
                                    item(key = "tg_proxy") {
                                        MenuNavItem(
                                            label = theme?.telegram_proxy_menu_label?.takeIf { it.isNotBlank() }
                                                ?: "Ускорить Telegram",
                                            fg = fg,
                                            onClick = {
                                                onOpenUrl(proxyUrl)
                                                menuOpen = false
                                                menuPage = MenuPage.ROOT
                                            },
                                        )
                                    }
                                }
                            }
                            if (vpnState == VpnState.CONNECTED) {
                                item(key = "tg_boost") {
                                    MenuNavItem(
                                        label = "Обновить канал Telegram",
                                        fg = fg,
                                        onClick = {
                                            onRefreshTelegramChannel()
                                            menuOpen = false
                                            menuPage = MenuPage.ROOT
                                        },
                                    )
                                }
                            }
                            item(key = "logout") {
                                MenuNavLogout(onClick = { onLogout(); menuOpen = false })
                            }
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
                    key(menuPage) {
                        when (menuPage) {
                        MenuPage.SUBSCRIPTION -> MenuSubscription(
                            profile = profile,
                            fg = fg,
                            onBack = { menuPage = MenuPage.ROOT },
                            onInitPayment = onInitPayment,
                            onOpenUrl = onOpenUrl,
                            onShowError = onShowError,
                        )
                        MenuPage.EXCEPTIONS -> AppExclusionsScreen(repo, palette) { menuPage = MenuPage.ROOT }
                        MenuPage.DNS -> MenuDnsScreen(repo, fg) { menuPage = MenuPage.ROOT }
                        MenuPage.VK_CRED -> MenuVkCredModeScreen(repo, fg) { menuPage = MenuPage.ROOT }
                        MenuPage.HASHES -> MenuHashesScreen(repo, fg) { menuPage = MenuPage.ROOT }
                        MenuPage.BONUSES -> {
                            val context = androidx.compose.ui.platform.LocalContext.current
                            MenuBonuses(
                                theme = theme,
                                palette = palette,
                                referralInfo = referralInfo,
                                referralCopyMsg = referralCopyMsg,
                                onCopyText = { text, okMsg ->
                                    val cm = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE)
                                        as? android.content.ClipboardManager
                                    if (cm != null) {
                                        cm.setPrimaryClip(android.content.ClipData.newPlainText("Silent VPN", text))
                                        referralCopyMsg = okMsg
                                    } else {
                                        referralCopyMsg = "Не удалось скопировать"
                                    }
                                },
                                promoCode = promoCode,
                                onPromoChange = { promoCode = it },
                                promoMsg = promoMsg,
                                onCheckPromo = { onCheckPromo(promoCode) { promoMsg = it } },
                                onBack = { menuPage = MenuPage.ROOT },
                            )
                        }
                        MenuPage.DEVICES -> MenuDevices(
                            profile,
                            fg,
                            sessionDeviceId,
                            vpnState,
                            onRenameDevice,
                            onDeleteDevice,
                            palette = palette,
                            borderColor = palette.border,
                            onlineColor = statusGreen,
                            offlineColor = palette.muted,
                        ) { menuPage = MenuPage.ROOT }
                        MenuPage.SUPPORT -> MenuSupport(
                            theme = theme,
                            fg = fg,
                            onOpenUrl = onOpenUrl,
                        ) { menuPage = MenuPage.ROOT }
                        MenuPage.ABOUT -> MenuSimplePage(
                            title = "Silent VPN",
                            body = "Версия ${com.silent.vpn.BuildConfig.VERSION_NAME}\nWireGuard-туннель через VK TURN/DTLS",
                            fg = fg,
                            focusKey = menuPage,
                        ) { menuPage = MenuPage.ROOT }
                        else -> Unit
                        }
                    }
                }
            }
        }

        SnackbarHost(snackbarHostState, modifier = Modifier.align(Alignment.BottomCenter))
        DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
    }
}

@Composable
private fun MenuSimplePage(
    title: String,
    body: String,
    fg: Color,
    focusKey: Any,
    onBack: () -> Unit,
) {
    val isTv = rememberIsTv()
    val backFocus = remember { FocusRequester() }
    LaunchedEffect(focusKey) {
        if (isTv) {
            kotlinx.coroutines.delay(180)
            runCatching { backFocus.requestFocus() }
        }
    }
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        if (isTv) {
            Box(
                modifier = Modifier
                    .padding(bottom = 16.dp)
                    .focusRequester(backFocus)
                    .tvConsumeFocusUp()
                    .defaultMinSize(minHeight = 36.dp)
                    .tvClickable(cornerRadius = 8.dp, ringOnTop = true, onClick = onBack),
                contentAlignment = Alignment.CenterStart,
            ) {
                Text(
                    "← Назад",
                    fontSize = 12.sp,
                    color = fg.copy(alpha = 0.4f),
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
        } else {
            TextButton(
                onClick = onBack,
                modifier = Modifier.padding(bottom = 16.dp),
            ) {
                Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
            }
        }
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        Text(body, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp))
    }
}

@Composable
private fun MenuSupport(
    theme: ThemeData?,
    fg: Color,
    onOpenUrl: (String) -> Unit,
    onBack: () -> Unit,
) {
    val muted = fg.copy(alpha = 0.5f)
    val channel = theme?.telegram_channel_url?.takeIf { it.isNotBlank() } ?: "https://t.me/silentvpn3"
    val support = theme?.support_url?.takeIf { it.isNotBlank() } ?: "https://t.me/silentvpn3?direct"
    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "support",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }
        Text("Поддержка", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        Text("По вопросам обратитесь через Telegram.", fontSize = 12.sp, color = muted, modifier = Modifier.padding(top = 8.dp, bottom = 16.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
            listOf("Канал" to channel, "Поддержка" to support).forEach { (label, url) ->
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally,
                    modifier = if (rememberIsTv()) {
                        Modifier.tvClickable(cornerRadius = 16.dp, onClick = { onOpenUrl(url) })
                    } else {
                        Modifier.clickable { onOpenUrl(url) }
                    },
                ) {
                    Box(
                        modifier = Modifier
                            .size(48.dp)
                            .background(Color(0xFFF3F4F6), RoundedCornerShape(16.dp)),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            painter = painterResource(R.drawable.ic_telegram),
                            contentDescription = label,
                            tint = Color.Unspecified,
                            modifier = Modifier.size(28.dp),
                        )
                    }
                    Text(label, fontSize = 11.sp, color = muted, modifier = Modifier.padding(top = 8.dp))
                }
            }
        }
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
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "subscription",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }
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
                TvPrimaryButton(
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
private fun MenuBonuses(
    theme: ThemeData?,
    palette: ThemePalette,
    referralInfo: com.silent.vpn.data.ReferralInfo?,
    referralCopyMsg: String,
    onCopyText: (String, String) -> Unit,
    promoCode: String,
    onPromoChange: (String) -> Unit,
    promoMsg: String,
    onCheckPromo: () -> Unit,
    onBack: () -> Unit,
) {
    val fg = palette.fg
    val bg = palette.bg
    val fieldColors = themeTextFieldColors(palette)
    val title = theme?.bonuses_title?.takeIf { it.isNotBlank() }
        ?: theme?.menu_bonuses_label?.takeIf { it.isNotBlank() }
        ?: "Бонусы"
    Column(modifier = Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp)) {
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "bonuses",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }
        Text(title, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        val intro = theme?.bonuses_intro_text?.takeIf { it.isNotBlank() }
            ?: theme?.bonuses_rules_text?.takeIf { it.isNotBlank() }
            ?: "Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — оба получаете +30 дней. Один бонус на одного друга, до 10 наград за 30 дней.\n\nПромокод: отдельная скидка или доп. дни к тарифу — вводится при регистрации или проверяется здесь.\n\nУсловия программы могут измениться."
        Text(
            intro,
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.5f),
            modifier = Modifier.padding(top = 8.dp, bottom = 12.dp),
        )
        Text(
            theme?.bonuses_referral_title?.takeIf { it.isNotBlank() } ?: "Ваша ссылка",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
        )
        Text(
            theme?.bonuses_referral_hint?.takeIf { it.isNotBlank() } ?: "Скопируйте и отправьте другу",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )
        OutlinedTextField(
            value = referralInfo?.referral_link ?: "…",
            onValueChange = {},
            readOnly = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        TvPrimaryButton(
            onClick = {
                val link = referralInfo?.referral_link ?: return@TvPrimaryButton
                onCopyText(link, "Ссылка скопирована")
            },
            colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = bg),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text(theme?.bonuses_copy_link_label ?: "Копировать ссылку", fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
        }
        if (referralInfo != null) {
            Text(
                "Приглашено: ${referralInfo.invited_count} · Награждено: ${referralInfo.rewarded_count}" +
                    if (referralInfo.pending_count > 0) " · Ожидают оплату: ${referralInfo.pending_count}" else "",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.5f),
                modifier = Modifier.padding(top = 8.dp),
            )
        }
        if (referralCopyMsg.isNotBlank()) {
            Text(referralCopyMsg, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 6.dp).fillMaxWidth(), textAlign = TextAlign.Center)
        }
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            theme?.bonuses_promo_title?.takeIf { it.isNotBlank() } ?: "Промокод",
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
        )
        Text(
            theme?.bonuses_promo_hint?.takeIf { it.isNotBlank() } ?: "Проверить скидку к тарифу",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.5f),
            modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
        )
        OutlinedTextField(
            value = promoCode,
            onValueChange = onPromoChange,
            placeholder = { Text("Введите код", color = palette.fieldPlaceholder) },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
        )
        TvPrimaryButton(
            onClick = onCheckPromo,
            colors = ButtonDefaults.buttonColors(containerColor = fg, contentColor = bg),
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        ) {
            Text("Проверить", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
        if (promoMsg.isNotBlank()) {
            Text(promoMsg, fontSize = 12.sp, color = fg.copy(alpha = 0.5f), modifier = Modifier.padding(top = 8.dp).fillMaxWidth(), textAlign = TextAlign.Center)
        }
        val footer = theme?.bonuses_rules_text?.takeIf { it.isNotBlank() }
        if (footer != null && footer != intro) {
            Text(
                footer,
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.5f),
                modifier = Modifier.padding(top = 16.dp),
            )
        }
    }
}

@Composable
private fun MenuDevices(
    profile: UserProfile?,
    fg: Color,
    sessionDeviceId: String?,
    vpnState: VpnState,
    onRenameDevice: (deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) -> Unit,
    onDeleteDevice: (deviceId: String, onResult: (Boolean, String?) -> Unit) -> Unit,
    palette: ThemePalette,
    borderColor: Color = Color(0xFFF3F4F6),
    onlineColor: Color = Color(0xFF16A34A),
    offlineColor: Color = Color(0xFFD1D5DB),
    onBack: () -> Unit,
) {
    var renameTarget by remember { mutableStateOf<DeviceInfo?>(null) }
    var renameText by remember { mutableStateOf("") }
    var renameSaving by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<DeviceInfo?>(null) }
    val fieldColors = themeTextFieldColors(palette)
    var deleteSaving by remember { mutableStateOf(false) }

    if (renameTarget != null) {
        AlertDialog(
            onDismissRequest = { if (!renameSaving) renameTarget = null },
            title = { Text("Приписать имя", fontSize = 14.sp) },
            text = {
                OutlinedTextField(
                    value = renameText,
                    onValueChange = { renameText = it.take(64) },
                    placeholder = { Text("Например: Мой телефон", color = palette.fieldPlaceholder) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                    colors = fieldColors,
                )
            },
            confirmButton = {
                TvTextButton(
                    enabled = !renameSaving,
                    onClick = {
                        val target = renameTarget ?: return@TvTextButton
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
                TvTextButton(onClick = { if (!renameSaving) renameTarget = null }) {
                    Text("Отмена")
                }
            },
        )
    }

    deleteTarget?.let { target ->
        val isSelf = !sessionDeviceId.isNullOrBlank() && target.id == sessionDeviceId
        AlertDialog(
            onDismissRequest = { if (!deleteSaving) deleteTarget = null },
            title = { Text("Удалить сессию", fontSize = 14.sp) },
            text = {
                Text(
                    if (isSelf) "Удалить эту сессию и выйти из аккаунта?" else "Удалить сессию этого устройства?",
                    fontSize = 13.sp,
                )
            },
            confirmButton = {
                TvTextButton(
                    enabled = !deleteSaving,
                    onClick = {
                        deleteSaving = true
                        onDeleteDevice(target.id) { ok, _ ->
                            deleteSaving = false
                            if (ok) deleteTarget = null
                        }
                    },
                ) { Text(if (deleteSaving) "…" else "Удалить") }
            },
            dismissButton = {
                TvTextButton(onClick = { if (!deleteSaving) deleteTarget = null }) {
                    Text("Отмена")
                }
            },
        )
    }

    Column(modifier = Modifier.fillMaxSize().padding(16.dp).verticalScroll(rememberScrollState())) {
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "devices",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }
        Text("Сессии", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg)
        val maxSlotsLabel = profile?.deviceLimitLabel() ?: "3"
        val maxSlots = profile?.max_devices?.takeIf { it > 0 } ?: Int.MAX_VALUE
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
        val onlineCount = if (profile?.is_admin == true || (profile?.max_devices ?: 3) <= 0) {
            serverOnline
        } else {
            serverOnline.coerceIn(0, maxSlots)
        }
        Text(
            "VPN онлайн: $onlineCount из $maxSlotsLabel",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.45f),
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Занято слотов: $slotsUsed из $maxSlotsLabel",
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
                            color = borderColor,
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
                        if (online) onlineColor else offlineColor,
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
                TvIconButton(
                    onClick = {
                        renameTarget = d
                        renameText = sessionCustomLabel(d).orEmpty()
                    },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Default.Edit, contentDescription = "Подписать", tint = fg.copy(alpha = 0.45f), modifier = Modifier.size(16.dp))
                }
                TvIconButton(
                    onClick = { deleteTarget = d },
                    modifier = Modifier.size(32.dp),
                ) {
                    Icon(Icons.Default.Close, contentDescription = "Удалить сессию", tint = fg.copy(alpha = 0.45f), modifier = Modifier.size(16.dp))
                }
            }
        }
    }
}
