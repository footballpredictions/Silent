package com.silent.vpn.ui.screens

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog
import com.silent.vpn.ui.components.LoginExpiredPanel
import com.silent.vpn.ui.components.SilentLogo
import com.silent.vpn.ui.theme.loginTextFieldColors
import com.silent.vpn.ui.theme.toLoginUi

private enum class LoginStep { AUTH, FORGOT }

@Composable
fun LoginScreen(
    theme: ThemeData? = null,
    initialEmail: String = "",
    initialPassword: String = "",
    initialRememberMe: Boolean = false,
    forgotSent: Boolean = false,
    onLogin: (email: String, password: String, rememberMe: Boolean) -> Unit,
    onRegister: (email: String, password: String, rememberMe: Boolean) -> Unit,
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
) {
    val ui = remember(theme) { theme.toLoginUi() }
    var step by remember { mutableStateOf(LoginStep.AUTH) }
    var tab by remember { mutableStateOf("login") }
    var email by remember(initialEmail) { mutableStateOf(initialEmail) }
    var password by remember(initialPassword) { mutableStateOf(initialPassword) }
    var showPassword by remember { mutableStateOf(false) }
    var rememberMe by remember(initialRememberMe) { mutableStateOf(initialRememberMe) }
    var showDebugLog by remember { mutableStateOf(false) }
    val fieldColors = loginTextFieldColors(ui)

    val rememberLabel = theme?.login_remember_me_label ?: "Запомнить меня"
    val forgotLabel = theme?.login_forgot_password_label ?: "Забыли пароль?"
    val forgotTitle = theme?.login_forgot_title ?: "Восстановление пароля"
    val forgotHint = theme?.login_forgot_instruction ?: "Введите email — мы отправим ссылку."

    val expiredMessage = statusMsg.ifBlank {
        "Время временного интернета истекло (2 мин). Закройте приложение и запустите снова."
    }
    val expiredBody = remember(expiredMessage) {
        expiredMessage
            .replace(Regex("^Время временного интернета истекло\\s*\\(2 мин\\)\\.?\\s*", RegexOption.IGNORE_CASE), "")
            .trim()
            .ifBlank { "Закройте приложение и откройте снова." }
    }

    LaunchedEffect(Unit) {
        onSyncBootstrap()
    }

    Column(
        modifier = Modifier.fillMaxSize().background(ui.bg).windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            DebugLogButton(onClick = { showDebugLog = true }, modifier = Modifier.align(Alignment.CenterEnd))
        }

        Column(
            modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp).padding(top = 24.dp, bottom = 20.dp),
        ) {
            Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                SilentLogo()
                Spacer(modifier = Modifier.height(12.dp))
                Text("SILENT VPN", color = ui.fg, fontWeight = FontWeight.Bold, fontSize = 16.sp, letterSpacing = 3.sp)
            }
            Spacer(modifier = Modifier.height(20.dp))

            if (step == LoginStep.AUTH) {
                Column {
                    if (!bootstrapExpired) {
                        when {
                            bootstrapConnecting -> {
                                Text(
                                    "Подключение… подождите",
                                    fontSize = 12.sp,
                                    color = ui.hint,
                                    modifier = Modifier.padding(bottom = 12.dp),
                                )
                            }
                            bootstrapReady -> {
                                val sec = bootstrapSecondsLeft
                                Text(
                                    when {
                                        sec != null -> statusMsg.ifBlank {
                                            "Канал готов. Осталось %d:%02d".format(sec / 60, sec % 60)
                                        }
                                        statusMsg.isNotBlank() -> statusMsg
                                        else -> "VPN включён"
                                    },
                                    fontSize = 12.sp,
                                    fontWeight = FontWeight.Medium,
                                    color = ui.green,
                                    modifier = Modifier.padding(bottom = 12.dp),
                                )
                            }
                            statusMsg.isNotBlank() -> {
                                Text(
                                    statusMsg,
                                    fontSize = 12.sp,
                                    color = ui.red,
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
                                    .clip(RoundedCornerShape(10.dp))
                                    .background(if (selected) ui.primaryBtnBg else Color.Transparent)
                                    .clickable(enabled = !bootstrapExpired) {
                                        tab = key
                                        onClearError()
                                        if (key == "login") onRegDoneDismiss()
                                    }
                                    .padding(vertical = 8.dp),
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
                                        placeholder = { Text("you@example.com", fontSize = 14.sp, color = ui.fieldPlaceholder) },
                                        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                                        shape = RoundedCornerShape(12.dp), colors = fieldColors,
                                    )
                                    Spacer(modifier = Modifier.height(12.dp))
                                    Text("Пароль", color = ui.label, fontSize = 12.sp)
                                    OutlinedTextField(
                                        value = password, onValueChange = { password = it }, modifier = Modifier.fillMaxWidth(),
                                        singleLine = true,
                                        visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                                        shape = RoundedCornerShape(12.dp), colors = fieldColors,
                                        trailingIcon = {
                                            IconButton(onClick = { showPassword = !showPassword }) {
                                                Icon(
                                                    imageVector = if (showPassword) Icons.Default.VisibilityOff else Icons.Default.Visibility,
                                                    contentDescription = if (showPassword) "Скрыть пароль" else "Показать пароль",
                                                    tint = ui.fg.copy(alpha = 0.6f),
                                                    modifier = Modifier.size(16.dp),
                                                )
                                            }
                                        },
                                    )
                                    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
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
                                        if (tab == "login") {
                                            TextButton(onClick = {
                                                onClearForgotSent()
                                                step = LoginStep.FORGOT
                                                onClearError()
                                            }) {
                                                Text(forgotLabel, fontSize = 11.sp, color = ui.linkColor)
                                            }
                                        }
                                    }
                                    if (!error.isNullOrBlank()) Text(error, color = ui.red, fontSize = 12.sp, modifier = Modifier.padding(bottom = 8.dp))
                                    Button(
                                        onClick = {
                                            if (tab == "login") onLogin(email.trim(), password, rememberMe)
                                            else onRegister(email.trim(), password, rememberMe)
                                        },
                                        enabled = !loading && bootstrapReady && email.isNotBlank() && password.isNotBlank(),
                                        modifier = Modifier.fillMaxWidth().height(48.dp),
                                        shape = RoundedCornerShape(12.dp),
                                        colors = ButtonDefaults.buttonColors(containerColor = ui.primaryBtnBg, contentColor = ui.primaryBtnFg),
                                    ) {
                                        if (loading) CircularProgressIndicator(modifier = Modifier.size(20.dp), color = ui.primaryBtnFg, strokeWidth = 2.dp)
                                        else Text(if (tab == "login") "Войти" else "Зарегистрироваться", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
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
                    TextButton(onClick = { onClearForgotSent() }, modifier = Modifier.fillMaxWidth()) {
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
                    Button(
                        onClick = { onForgotPassword(email.trim()) },
                        enabled = !loading && email.isNotBlank(),
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = ui.primaryBtnBg, contentColor = ui.primaryBtnFg),
                    ) { Text("Отправить письмо") }
                }
                TextButton(onClick = { onClearForgotSent(); step = LoginStep.AUTH; onClearError() }) {
                    Text("← Назад к входу", fontSize = 12.sp, color = ui.hint)
                }
                }
            }
        }
    }
    DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
}
