package com.silent.vpn.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.slideInVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import com.silent.vpn.ui.components.SilentLogo
import com.silent.vpn.ui.theme.loginTextFieldColors
import com.silent.vpn.ui.theme.toLoginUi

private enum class LoginStep { HASH, AUTH, FORGOT, RESET }

@Composable
fun LoginScreen(
    theme: ThemeData? = null,
    initialEmail: String = "",
    initialRememberMe: Boolean = false,
    resetToken: String? = null,
    forgotSent: Boolean = false,
    onLogin: (email: String, password: String, rememberMe: Boolean) -> Unit,
    onRegister: (email: String, password: String, rememberMe: Boolean) -> Unit,
    onForgotPassword: (email: String) -> Unit,
    onResetPassword: (token: String, newPassword: String) -> Unit,
    onClearResetToken: () -> Unit,
    loading: Boolean,
    error: String?,
    regDone: Boolean,
    regEmail: String,
    bootstrapHash: String?,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    onConnect: (String) -> Unit,
    onOpenVkLink: (String) -> Unit,
    onClearError: () -> Unit,
    onRegDoneDismiss: () -> Unit,
) {
    val ui = remember(theme) { theme.toLoginUi() }
    var step by remember {
        mutableStateOf(
            when {
                !resetToken.isNullOrBlank() -> LoginStep.RESET
                bootstrapReady -> LoginStep.AUTH
                else -> LoginStep.HASH
            },
        )
    }
    var tab by remember { mutableStateOf("login") }
    var email by remember(initialEmail) { mutableStateOf(initialEmail) }
    var password by remember { mutableStateOf("") }
    var newPassword by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var rememberMe by remember(initialRememberMe) { mutableStateOf(initialRememberMe) }
    var showDebugLog by remember { mutableStateOf(false) }
    val fieldColors = loginTextFieldColors(ui)

    val step2Title = theme?.login_step2_title ?: "Шаг 2 — вход или регистрация"
    val rememberLabel = theme?.login_remember_me_label ?: "Запомнить меня"
    val forgotLabel = theme?.login_forgot_password_label ?: "Забыли пароль?"
    val forgotTitle = theme?.login_forgot_title ?: "Восстановление пароля"
    val forgotHint = theme?.login_forgot_instruction ?: "Введите email — мы отправим ссылку."
    val resetTitle = theme?.login_reset_title ?: "Новый пароль"
    val resetBtn = theme?.login_reset_button_text ?: "Сохранить пароль"
    val vkUrl = theme?.login_vk_mobile_url ?: "https://vk.com/calls"

    LaunchedEffect(resetToken) {
        if (!resetToken.isNullOrBlank()) step = LoginStep.RESET
    }

    LaunchedEffect(bootstrapReady) {
        if (bootstrapReady && step == LoginStep.HASH) step = LoginStep.AUTH
        if (!bootstrapReady && statusMsg.contains("истекло", ignoreCase = true)) step = LoginStep.HASH
    }

    Column(
        modifier = Modifier.fillMaxSize().background(ui.bg).windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().background(ui.headerBg).padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Text("SILENT VPN", color = ui.headerFg, fontSize = 11.sp, letterSpacing = 2.sp, modifier = Modifier.align(Alignment.CenterStart))
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

            if (step == LoginStep.HASH) {
                HashInputSection(
                    ui = ui,
                    theme = theme,
                    bootstrapHash = bootstrapHash,
                    statusMsg = statusMsg,
                    bootstrapConnecting = bootstrapConnecting,
                    bootstrapReady = bootstrapReady,
                    onConnect = onConnect,
                    onOpenVkLink = { onOpenVkLink(vkUrl) },
                    showDivider = false,
                )
                if (bootstrapReady) {
                    TextButton(onClick = { step = LoginStep.AUTH }, modifier = Modifier.fillMaxWidth()) {
                        Text("→ К шагу 2 — вход или регистрация", fontSize = 11.sp, color = ui.hint)
                    }
                }
            }

            AnimatedVisibility(
                visible = step == LoginStep.AUTH,
                enter = fadeIn() + slideInVertically { it / 4 },
            ) {
                Column {
                    Text(step2Title, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = ui.fg, modifier = Modifier.padding(bottom = 12.dp))
                    Row(
                        modifier = Modifier.fillMaxWidth().background(ui.tabBg, RoundedCornerShape(12.dp)).padding(4.dp),
                    ) {
                        listOf("login" to "Войти", "register" to "Регистрация").forEach { (key, label) ->
                            val selected = tab == key
                            Box(
                                modifier = Modifier.weight(1f).background(
                                    if (selected) ui.primaryBtnBg else Color.Transparent,
                                    RoundedCornerShape(10.dp),
                                ).padding(vertical = 8.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                TextButton(onClick = { tab = key; onClearError(); if (key == "login") onRegDoneDismiss() }, contentPadding = PaddingValues(0.dp)) {
                                    Text(label, color = if (selected) ui.primaryBtnFg else ui.hint, fontSize = 12.sp, fontWeight = FontWeight.Medium)
                                }
                            }
                        }
                    }
                    Spacer(modifier = Modifier.height(16.dp))

                    if (regDone) {
                        Column(modifier = Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                            Spacer(modifier = Modifier.height(32.dp))
                            Text("Подтвердите email", color = ui.fg, fontWeight = FontWeight.Medium, fontSize = 14.sp)
                            Text("Ссылка отправлена на $regEmail", color = ui.hint, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
                            Text("Откройте её в браузере — VPN должен быть включён", color = ui.hint, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 2.dp))
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
                            placeholder = { Text("••••••••", fontSize = 14.sp, color = ui.fieldPlaceholder) },
                            singleLine = true,
                            visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                            shape = RoundedCornerShape(12.dp), colors = fieldColors,
                            trailingIcon = {
                                TextButton(onClick = { showPassword = !showPassword }) {
                                    Text(if (showPassword) "Скрыть" else "Показать", fontSize = 11.sp, color = ui.hint)
                                }
                            },
                        )
                        Row(modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = rememberMe, onCheckedChange = { rememberMe = it }, colors = CheckboxDefaults.colors(checkedColor = ui.fg))
                                Text(rememberLabel, fontSize = 12.sp, color = ui.hint)
                            }
                            if (tab == "login") {
                                TextButton(onClick = { step = LoginStep.FORGOT; onClearError() }) {
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
                            enabled = !loading && email.isNotBlank() && password.isNotBlank(),
                            modifier = Modifier.fillMaxWidth().height(48.dp),
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = ui.primaryBtnBg, contentColor = ui.primaryBtnFg),
                        ) {
                            if (loading) CircularProgressIndicator(modifier = Modifier.size(20.dp), color = ui.primaryBtnFg, strokeWidth = 2.dp)
                            else Text(if (tab == "login") "Войти" else "Зарегистрироваться", fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                        }
                        TextButton(onClick = { step = LoginStep.HASH }, modifier = Modifier.fillMaxWidth()) {
                            Text("← Изменить хеш VK", fontSize = 11.sp, color = ui.hint)
                        }
                    }
                }
            }

            if (step == LoginStep.FORGOT) {
                Text(forgotTitle, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = ui.fg)
                Text(forgotHint, fontSize = 12.sp, color = ui.hint, modifier = Modifier.padding(top = 8.dp, bottom = 16.dp))
                if (forgotSent) {
                    Text("Если email зарегистрирован, письмо отправлено.", color = ui.green, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 24.dp))
                    Text("Откройте ссылку в браузере — VPN должен быть включён", color = ui.hint, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 24.dp))
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
                TextButton(onClick = { step = if (bootstrapReady) LoginStep.AUTH else LoginStep.HASH; onClearError() }) {
                    Text("← Назад", fontSize = 12.sp, color = ui.hint)
                }
            }

            if (step == LoginStep.RESET && !resetToken.isNullOrBlank()) {
                if (!bootstrapReady) {
                    HashInputSection(
                        ui = ui,
                        theme = theme,
                        bootstrapHash = bootstrapHash,
                        statusMsg = statusMsg,
                        bootstrapConnecting = bootstrapConnecting,
                        bootstrapReady = bootstrapReady,
                        onConnect = onConnect,
                        onOpenVkLink = { onOpenVkLink(vkUrl) },
                        showDivider = true,
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        "Для смены пароля нужен VPN (шаг 1). Подключитесь выше.",
                        fontSize = 12.sp,
                        color = ui.hint,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp),
                    )
                }
                Text(resetTitle, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = ui.fg)
                Spacer(modifier = Modifier.height(12.dp))
                OutlinedTextField(
                    value = newPassword, onValueChange = { newPassword = it }, modifier = Modifier.fillMaxWidth(),
                    label = { Text("Новый пароль") },
                    visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    shape = RoundedCornerShape(12.dp), colors = fieldColors,
                    trailingIcon = {
                        TextButton(onClick = { showPassword = !showPassword }) {
                            Text(if (showPassword) "Скрыть" else "Показать", fontSize = 11.sp, color = ui.hint)
                        }
                    },
                )
                if (!error.isNullOrBlank()) Text(error, color = ui.red, fontSize = 12.sp, modifier = Modifier.padding(top = 8.dp))
                Spacer(modifier = Modifier.height(12.dp))
                Button(
                    onClick = { onResetPassword(resetToken, newPassword) },
                    enabled = !loading && newPassword.length >= 8 && bootstrapReady,
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = ui.primaryBtnBg, contentColor = ui.primaryBtnFg),
                ) { Text(resetBtn) }
                TextButton(onClick = { onClearResetToken(); step = if (bootstrapReady) LoginStep.AUTH else LoginStep.HASH }) {
                    Text("← Назад", fontSize = 12.sp, color = ui.hint)
                }
            }
        }
    }
    DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
}
