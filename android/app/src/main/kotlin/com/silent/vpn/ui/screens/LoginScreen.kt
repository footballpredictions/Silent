package com.silent.vpn.ui.screens

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
import com.silent.vpn.ui.theme.LoginUi
import com.silent.vpn.ui.theme.loginTextFieldColors
import com.silent.vpn.ui.theme.toLoginUi

@Composable
fun LoginScreen(
    theme: ThemeData? = null,
    initialEmail: String = "",
    onLogin: (email: String, password: String) -> Unit,
    onRegister: (email: String, password: String) -> Unit,
    loading: Boolean,
    error: String?,
    regDone: Boolean,
    regEmail: String,
    hashReady: Boolean,
    bootstrapHash: String?,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    onConnect: (String) -> Unit,
    onClearError: () -> Unit,
    onRegDoneDismiss: () -> Unit,
) {
    val ui = remember(theme) { theme.toLoginUi() }
    var tab by remember { mutableStateOf("login") }
    var email by remember(initialEmail) { mutableStateOf(initialEmail) }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var showDebugLog by remember { mutableStateOf(false) }
    val fieldColors = loginTextFieldColors(ui)

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(ui.bg)
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(ui.headerBg)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Text(
                "SILENT VPN",
                color = ui.headerFg,
                fontSize = 11.sp,
                letterSpacing = 2.sp,
                modifier = Modifier.align(Alignment.CenterStart),
            )
            DebugLogButton(
                onClick = { showDebugLog = true },
                modifier = Modifier.align(Alignment.CenterEnd),
            )
        }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp)
                .padding(top = 24.dp, bottom = 20.dp),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                SilentLogo()
                Spacer(modifier = Modifier.height(12.dp))
                Text(
                    "SILENT VPN",
                    color = ui.fg,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    letterSpacing = 3.sp,
                )
            }

            Spacer(modifier = Modifier.height(20.dp))

            HashInputSection(
                ui = ui,
                bootstrapHash = bootstrapHash,
                statusMsg = statusMsg,
                bootstrapConnecting = bootstrapConnecting,
                bootstrapReady = bootstrapReady,
                onConnect = onConnect,
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(ui.tabBg, RoundedCornerShape(12.dp))
                    .padding(4.dp),
            ) {
                listOf("login" to "Войти", "register" to "Регистрация").forEach { (key, label) ->
                    val selected = tab == key
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .background(
                                if (selected) ui.primaryBtnBg else Color.Transparent,
                                RoundedCornerShape(10.dp),
                            )
                            .padding(vertical = 8.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        TextButton(
                            onClick = {
                                tab = key
                                onClearError()
                                if (key == "login") onRegDoneDismiss()
                            },
                            contentPadding = PaddingValues(0.dp),
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

            Spacer(modifier = Modifier.height(16.dp))

            if (regDone) {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Spacer(modifier = Modifier.height(32.dp))
                    Text(
                        "Подтвердите email",
                        color = ui.fg,
                        fontWeight = FontWeight.Medium,
                        fontSize = 14.sp,
                    )
                    Text(
                        "Ссылка отправлена на $regEmail",
                        color = ui.hint,
                        fontSize = 12.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    TextButton(onClick = {
                        tab = "login"
                        onRegDoneDismiss()
                    }) {
                        Text("Войти", fontSize = 12.sp, color = ui.fg)
                    }
                }
            } else {
                Text("Email", color = ui.label, fontSize = 12.sp)
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = {
                        Text("you@example.com", fontSize = 14.sp, color = ui.fieldPlaceholder)
                    },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    shape = RoundedCornerShape(12.dp),
                    colors = fieldColors,
                )

                Spacer(modifier = Modifier.height(12.dp))

                Text("Пароль", color = ui.label, fontSize = 12.sp)
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = {
                        Text("••••••••", fontSize = 14.sp, color = ui.fieldPlaceholder)
                    },
                    singleLine = true,
                    visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    shape = RoundedCornerShape(12.dp),
                    colors = fieldColors,
                    trailingIcon = {
                        TextButton(onClick = { showPassword = !showPassword }) {
                            Text(
                                if (showPassword) "Скрыть" else "Показать",
                                fontSize = 11.sp,
                                color = ui.hint,
                            )
                        }
                    },
                )

                if (!error.isNullOrBlank()) {
                    Text(
                        error,
                        color = ui.red,
                        fontSize = 12.sp,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }

                Spacer(modifier = Modifier.height(16.dp))

                Button(
                    onClick = {
                        if (tab == "login") onLogin(email.trim(), password)
                        else onRegister(email.trim(), password)
                    },
                    enabled = !loading && email.isNotBlank() && password.isNotBlank(),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = ui.primaryBtnBg,
                        contentColor = ui.primaryBtnFg,
                        disabledContainerColor = ui.primaryBtnBg.copy(alpha = 0.4f),
                        disabledContentColor = ui.primaryBtnFg.copy(alpha = 0.5f),
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
    DebugLogDialog(visible = showDebugLog, onDismiss = { showDebugLog = false })
}
