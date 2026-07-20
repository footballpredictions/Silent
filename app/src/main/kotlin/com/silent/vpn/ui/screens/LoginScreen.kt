package com.silent.vpn.ui.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusProperties
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.BuildConfig
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.components.BrandHeader
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog
import com.silent.vpn.ui.components.LoginExpiredPanel
import com.silent.vpn.ui.components.ThemeModeToggle
import com.silent.vpn.ui.components.resolveThemeAssetUrl
import com.silent.vpn.ui.theme.AppearanceMode
import com.silent.vpn.ui.theme.DarkSystemBarStrip
import com.silent.vpn.ui.theme.displayAppName
import com.silent.vpn.ui.theme.needsNeonGlow
import com.silent.vpn.ui.theme.neonShadow
import com.silent.vpn.ui.theme.toLoginUi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.graphics.Shadow
import com.silent.vpn.ui.tv.TvIconButton
import com.silent.vpn.ui.tv.TvPrimaryButton
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.util.rememberIsTv
import com.silent.vpn.ui.theme.loginTextFieldColors

private enum class LoginStep { AUTH, FORGOT }

private fun isInternalTransportStatus(msg: String): Boolean {
    val m = msg.trim()
    return m.equals("Ожидание данных…", ignoreCase = true) ||
        m.equals("Ожидание данных...", ignoreCase = true) ||
        m.startsWith("Трафик:", ignoreCase = true)
}

/** Ошибки bootstrap — красным; промежуточные «Подключение VPN…» в UI не показываем. */
private fun isBootstrapFailureMessage(msg: String): Boolean {
    val m = msg.trim()
    if (m.isBlank() || isInternalTransportStatus(m)) return false
    if (m.contains("Канал готов", ignoreCase = true)) return false
    if (m.contains("Подтвердите email", ignoreCase = true)) return false
    if (m.contains("Откройте ссылку", ignoreCase = true)) return false
    if (m.startsWith("Подключение", ignoreCase = true)) return false
    return true
}

@Composable
fun LoginScreen(
    theme: ThemeData? = null,
    initialEmail: String = "",
    initialPassword: String = "",
    initialRememberMe: Boolean = false,
    initialReferralOrPromo: String = "",
    forgotSent: Boolean = false,
    onLogin: (email: String, password: String, rememberMe: Boolean) -> Unit,
    onRegister: (email: String, password: String, rememberMe: Boolean, referralOrPromo: String) -> Unit,
    onForgotPassword: (email: String) -> Unit,
    onClearForgotSent: () -> Unit = {},
    loading: Boolean,
    error: String?,
    regDone: Boolean,
    regEmail: String,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    bootstrapSecondsLeft: Int? = null,
    bootstrapExpired: Boolean = false,
    onClearError: () -> Unit,
    onRegDoneDismiss: () -> Unit,
    onSyncBootstrap: () -> Unit = {},
    onCloseApp: () -> Unit = {},
    appearanceMode: AppearanceMode = AppearanceMode.LIGHT,
    onToggleAppearance: () -> Unit = {},
) {
    val ui = remember(theme, appearanceMode) { theme.toLoginUi(appearanceMode) }
    var step by remember { mutableStateOf(LoginStep.AUTH) }
    var tab by remember(initialReferralOrPromo) {
        mutableStateOf(if (initialReferralOrPromo.isNotBlank()) "register" else "login")
    }
    var email by remember(initialEmail) { mutableStateOf(initialEmail) }
    var password by remember(initialPassword) { mutableStateOf(initialPassword) }
    var referralOrPromo by remember(initialReferralOrPromo) { mutableStateOf(initialReferralOrPromo) }
    var showPassword by remember { mutableStateOf(false) }
    var rememberMe by remember(initialRememberMe) { mutableStateOf(initialRememberMe) }
    var showDebugLog by remember { mutableStateOf(false) }
    val rememberMeFocus = remember { FocusRequester() }
    val fieldColors = loginTextFieldColors(ui)
    val isTv = rememberIsTv()
    val contentPadding = if (isTv) 48.dp else 20.dp
    val fieldFontSize = if (isTv) 16.sp else 14.sp
    val btnHeight = if (isTv) 56.dp else 48.dp

    val rememberLabel = theme?.login_remember_me_label ?: "Запомнить меня"
    val forgotLabel = theme?.login_forgot_password_label ?: "Забыли пароль?"
    val forgotTitle = theme?.login_forgot_title ?: "Восстановление пароля"
    val forgotHint = theme?.login_forgot_instruction ?: "Введите email — мы отправим ссылку."
    val refPromoLabel = theme?.register_referral_or_promo_label ?: "Промокод или реферальный код"
    val refPromoHint = theme?.register_referral_or_promo_hint ?: "Необязательно"

    LaunchedEffect(initialReferralOrPromo) {
        if (initialReferralOrPromo.isNotBlank()) {
            referralOrPromo = initialReferralOrPromo
            tab = "register"
        }
    }

    val bootstrapMin = if (isTv) 3 else 2
    val expiredMessage = statusMsg.ifBlank {
        "Время временного интернета истекло ($bootstrapMin мин). Закройте приложение и запустите снова."
    }
    val expiredBody = remember(expiredMessage) {
        expiredMessage
            .replace(Regex("^Время временного интернета истекло\\s*\\(\\d+ мин\\)\\.?\\s*", RegexOption.IGNORE_CASE), "")
            .trim()
            .ifBlank { "Закройте приложение и откройте снова." }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(if (ui.dark) DarkSystemBarStrip else ui.bg)
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .background(ui.bg),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Row(
                modifier = Modifier.align(Alignment.CenterEnd),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                ThemeModeToggle(
                    mode = appearanceMode,
                    onToggle = onToggleAppearance,
                    color = ui.fg,
                )
                DebugLogButton(onClick = { showDebugLog = true })
            }
        }

        Column(
            modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = contentPadding).padding(top = if (isTv) 32.dp else 24.dp, bottom = 20.dp),
        ) {
            Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                BrandHeader(
                    textColor = ui.fg,
                    appTitle = displayAppName(theme),
                    // Лого из темы — только DEBUG, пока проверяем оформление
                    logoUrl = if (!BuildConfig.DEBUG) null
                    else resolveThemeAssetUrl(
                        theme?.logo_url,
                        "https://${com.silent.vpn.data.SilentRepository.DEFAULT_SERVER_HOST}",
                    ).ifBlank { null },
                )
            }
            Spacer(modifier = Modifier.height(20.dp))

            if (step == LoginStep.AUTH) {
                Column {
                    if (!bootstrapExpired) {
                        when {
                            bootstrapReady -> {
                                val sec = bootstrapSecondsLeft
                                val readyText = when {
                                    statusMsg.contains("Канал готов", ignoreCase = true) -> statusMsg
                                    sec != null ->
                                        "Канал готов. Осталось %d:%02d — войдите или зарегистрируйтесь"
                                            .format(sec / 60, sec % 60)
                                    statusMsg.isNotBlank() && !isInternalTransportStatus(statusMsg) -> statusMsg
                                    else -> "Канал готов — войдите или зарегистрируйтесь"
                                }
                                Text(
                                    readyText,
                                    fontSize = if (isTv) 14.sp else 12.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = ui.green,
                                    modifier = Modifier.padding(bottom = 12.dp),
                                )
                            }
                            isBootstrapFailureMessage(statusMsg) -> {
                                Text(
                                    statusMsg,
                                    fontSize = if (isTv) 14.sp else 12.sp,
                                    color = ui.red,
                                    modifier = Modifier.padding(bottom = 12.dp),
                                )
                            }
                            else -> {
                                Text(
                                    "Подключение… подождите",
                                    fontSize = if (isTv) 14.sp else 12.sp,
                                    color = ui.hint,
                                    modifier = Modifier.padding(bottom = 12.dp),
                                )
                            }
                        }
                    }

                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .alpha(if (bootstrapExpired) 0.4f else 1f)
                            .background(ui.tabBg, RoundedCornerShape(12.dp))
                            .padding(4.dp),
                    ) {
                        listOf("login" to "Войти", "register" to "Регистрация").forEach { (key, label) ->
                            val selected = tab == key
                            Box(
                                modifier = Modifier
                                    .weight(1f)
                                    .then(
                                        if (isTv) {
                                            Modifier.tvClickable(
                                                enabled = !bootstrapExpired,
                                                cornerRadius = 10.dp,
                                                ringOnly = true,
                                                onClick = {
                                                    tab = key
                                                    onClearError()
                                                    if (key == "login") onRegDoneDismiss()
                                                },
                                            )
                                        } else {
                                            Modifier.clickable(enabled = !bootstrapExpired) {
                                                tab = key
                                                onClearError()
                                                if (key == "login") onRegDoneDismiss()
                                            }
                                        },
                                    ),
                            ) {
                                Box(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(if (selected) ui.primaryBtnBg else Color.Transparent)
                                        .padding(vertical = if (isTv) 12.dp else 8.dp),
                                    contentAlignment = Alignment.Center,
                                ) {
                                    Text(
                                        label,
                                        color = if (selected) ui.primaryBtnFg else ui.hint,
                                        fontSize = 12.sp,
                                        fontWeight = FontWeight.Medium,
                                    )
                                }
                            }
                        }
                    }

                    AnimatedContent(
                        targetState = bootstrapExpired,
                        label = "loginAuthBody",
                        transitionSpec = {
                            fadeIn(tween(220, easing = FastOutSlowInEasing))
                                .togetherWith(fadeOut(tween(180, easing = FastOutSlowInEasing)))
                        },
                    ) { expired ->
                        if (expired) {
                            LoginExpiredPanel(
                                fg = ui.fg,
                                hint = ui.hint,
                                accentColor = ui.red,
                                primaryBtnBg = ui.primaryBtnBg,
                                primaryBtnFg = ui.primaryBtnFg,
                                body = expiredBody,
                                onCloseApp = onCloseApp,
                                modifier = Modifier.padding(top = 16.dp),
                            )
                        } else {
                            Column {
                                Spacer(modifier = Modifier.height(16.dp))

                                if (regDone) {
                                    Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                                        Spacer(modifier = Modifier.height(32.dp))
                                        Text("Подтвердите email", color = ui.fg, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                                        Text("Ссылка отправлена на $regEmail", color = ui.hint, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
                                        Text("Откройте ссылку из письма (браузер или почта) — временный VPN включён", color = ui.hint, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 2.dp))
                                        TextButton(onClick = { tab = "login"; onRegDoneDismiss() }) { Text("Войти", fontSize = 12.sp, color = ui.fg) }
                                    }
                                } else {
                                    Text("Email", color = ui.label, fontSize = 12.sp)
                                    OutlinedTextField(
                                        value = email, onValueChange = { email = it }, modifier = Modifier.fillMaxWidth(),
                                        placeholder = { Text("you@example.com", fontSize = fieldFontSize, color = ui.fieldPlaceholder) },
                                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                                        shape = RoundedCornerShape(12.dp), colors = fieldColors,
                                    )
                                    Spacer(modifier = Modifier.height(12.dp))
                                    Text("Пароль", color = ui.label, fontSize = 12.sp)
                                    OutlinedTextField(
                                        value = password, onValueChange = { password = it },
                                        modifier = Modifier
                                            .fillMaxWidth()
                                            .then(
                                                if (isTv) {
                                                    Modifier.onPreviewKeyEvent { event ->
                                                        if (
                                                            event.type == KeyEventType.KeyDown &&
                                                            event.key == Key.DirectionDown
                                                        ) {
                                                            rememberMeFocus.requestFocus()
                                                            true
                                                        } else {
                                                            false
                                                        }
                                                    }
                                                } else {
                                                    Modifier
                                                },
                                            ),
                                        singleLine = true,
                                        visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                                        shape = RoundedCornerShape(12.dp), colors = fieldColors,
                                        trailingIcon = {
                                            TvIconButton(onClick = { showPassword = !showPassword }) {
                                                Icon(
                                                    imageVector = if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                                    contentDescription = if (showPassword) "Скрыть пароль" else "Показать пароль",
                                                    tint = ui.fg.copy(alpha = 0.6f),
                                                    modifier = Modifier.size(16.dp),
                                                )
                                            }
                                        },
                                    )
                                    if (tab == "register") {
                                        Spacer(modifier = Modifier.height(12.dp))
                                        Text(refPromoLabel, color = ui.label, fontSize = 12.sp)
                                        OutlinedTextField(
                                            value = referralOrPromo,
                                            onValueChange = { referralOrPromo = it },
                                            modifier = Modifier.fillMaxWidth(),
                                            placeholder = { Text(refPromoHint, fontSize = fieldFontSize, color = ui.fieldPlaceholder) },
                                            singleLine = true,
                                            shape = RoundedCornerShape(12.dp),
                                            colors = fieldColors,
                                        )
                                    }
                                    Row(
                                        modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                                        horizontalArrangement = Arrangement.SpaceBetween,
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        if (isTv) {
                                            Row(
                                                verticalAlignment = Alignment.CenterVertically,
                                                modifier = Modifier.weight(1f, fill = false),
                                            ) {
                                                Box(
                                                    modifier = Modifier
                                                        .size(48.dp)
                                                        .focusRequester(rememberMeFocus)
                                                        .focusProperties { canFocus = !bootstrapExpired }
                                                        .tvClickable(
                                                            enabled = !bootstrapExpired,
                                                            cornerRadius = 6.dp,
                                                            ringOnly = true,
                                                            onClick = { rememberMe = !rememberMe },
                                                        ),
                                                    contentAlignment = Alignment.Center,
                                                ) {
                                                    Box(
                                                        modifier = Modifier
                                                            .size(20.dp)
                                                            .clip(RoundedCornerShape(4.dp))
                                                            .border(
                                                                1.dp,
                                                                if (rememberMe) ui.fg else ui.border,
                                                                RoundedCornerShape(4.dp),
                                                            )
                                                            .background(
                                                                if (rememberMe) ui.fg else Color.Transparent,
                                                                RoundedCornerShape(4.dp),
                                                            ),
                                                        contentAlignment = Alignment.Center,
                                                    ) {
                                                        if (rememberMe) {
                                                            Icon(
                                                                Icons.Default.Check,
                                                                contentDescription = null,
                                                                tint = ui.bg,
                                                                modifier = Modifier.size(14.dp),
                                                            )
                                                        }
                                                    }
                                                }
                                                Text(
                                                    rememberLabel,
                                                    fontSize = 12.sp,
                                                    color = ui.hint,
                                                    modifier = Modifier.padding(start = 8.dp, end = 8.dp),
                                                )
                                            }
                                        } else {
                                            Row(verticalAlignment = Alignment.CenterVertically) {
                                                Checkbox(
                                                    checked = rememberMe,
                                                    onCheckedChange = { rememberMe = it },
                                                    colors = CheckboxDefaults.colors(
                                                        checkedColor = ui.fg,
                                                        checkmarkColor = ui.bg,
                                                        uncheckedColor = ui.border,
                                                    ),
                                                )
                                                Text(rememberLabel, fontSize = 12.sp, color = ui.hint)
                                            }
                                        }
                                        if (tab == "login") {
                                            TvTextButton(onClick = {
                                                onClearForgotSent()
                                                step = LoginStep.FORGOT
                                                onClearError()
                                            }) {
                                                Text(
                                                    forgotLabel,
                                                    fontSize = 11.sp,
                                                    color = ui.linkColor,
                                                    style = TextStyle(
                                                        shadow = if (needsNeonGlow(ui.linkColor, ui.dark)) neonShadow(ui.linkColor) else null,
                                                    ),
                                                )
                                            }
                                        }
                                    }
                                    if (!error.isNullOrBlank()) Text(error, color = ui.red, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
                                    TvPrimaryButton(
                                        onClick = {
                                            if (tab == "login") onLogin(email.trim(), password, rememberMe)
                                            else onRegister(email.trim(), password, rememberMe, referralOrPromo.trim())
                                        },
                                        enabled = !loading && bootstrapReady && email.isNotBlank() && password.isNotBlank(),
                                        modifier = Modifier.fillMaxWidth().height(btnHeight),
                                        shape = RoundedCornerShape(12.dp),
                                        colors = ButtonDefaults.buttonColors(
                                            containerColor = ui.primaryBtnBg,
                                            contentColor = ui.primaryBtnFg,
                                        ),
                                    ) {
                                        if (loading) {
                                            CircularProgressIndicator(
                                                modifier = Modifier.size(20.dp),
                                                color = ui.primaryBtnFg,
                                                strokeWidth = 2.dp,
                                            )
                                        } else {
                                            Text(
                                                if (tab == "login") "Войти" else "Зарегистрироваться",
                                                fontWeight = FontWeight.SemiBold,
                                                fontSize = 14.sp,
                                            )
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if (step == LoginStep.FORGOT) {
                if (bootstrapExpired) {
                    LoginExpiredPanel(
                        fg = ui.fg,
                        hint = ui.hint,
                        accentColor = ui.red,
                        primaryBtnBg = ui.primaryBtnBg,
                        primaryBtnFg = ui.primaryBtnFg,
                        body = expiredBody,
                        onCloseApp = onCloseApp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                } else {
                Text(forgotTitle, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = ui.fg)
                Text(forgotHint, fontSize = 12.sp, color = ui.hint, modifier = Modifier.padding(top = 8.dp, bottom = 16.dp))
                if (forgotSent) {
                    Text("Если email зарегистрирован, письмо отправлено.", color = ui.green, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 24.dp))
                    Text(
                        "Откройте ссылку из письма в браузере или почте — смените пароль на странице сайта, затем войдите в приложение.",
                        color = ui.hint,
                        fontSize = 11.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 16.dp),
                    )
                    TvTextButton(onClick = { onClearForgotSent() }, modifier = Modifier.fillMaxWidth()) {
                        Text("Отправить письмо снова", fontSize = 12.sp, color = ui.linkColor)
                    }
                } else {
                    OutlinedTextField(
                        value = email, onValueChange = { email = it }, modifier = Modifier.fillMaxWidth(),
                        label = { Text("Email") }, singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                        shape = RoundedCornerShape(12.dp), colors = fieldColors,
                    )
                    if (!error.isNullOrBlank()) Text(error, color = ui.red, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
                    Spacer(modifier = Modifier.height(12.dp))
                    TvPrimaryButton(
                        onClick = { onForgotPassword(email.trim()) },
                        enabled = !loading && email.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = ui.primaryBtnBg, contentColor = ui.primaryBtnFg),
                    ) { Text("Отправить письмо") }
                }
                TvTextButton(onClick = { onClearForgotSent(); step = LoginStep.AUTH; onClearError() }) {
                    Text("← Назад к входу", fontSize = 12.sp, color = ui.hint)
                }
                }
            }
        }
    }
    DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
}
