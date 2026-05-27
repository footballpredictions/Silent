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
import com.silent.vpn.ui.components.DebugLogButton
import com.silent.vpn.ui.components.DebugLogDialog

@Composable
fun LoginScreen(
    initialEmail: String = "",
    onLogin: (email: String, password: String) -> Unit,
    onRegister: (email: String, password: String) -> Unit,
    loading: Boolean,
    error: String?,
    regDone: Boolean,
    regEmail: String,
    vkReady: Boolean,
    vkUserId: Long?,
    bootstrapHash: String?,
    vkMsg: String,
    onLinkVk: () -> Unit,
    onClearError: () -> Unit,
    onRegDoneDismiss: () -> Unit,
) {
    var tab by remember { mutableStateOf("login") }
    var email by remember(initialEmail) { mutableStateOf(initialEmail) }
    var password by remember { mutableStateOf("") }
    var showPassword by remember { mutableStateOf(false) }
    var showDebugLog by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing),
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(Color.Black)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            Text(
                "SILENT VPN",
                color = Color(0xFF6B7280),
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
                Box(
                    modifier = Modifier
                        .size(56.dp)
                        .background(Color.Black, RoundedCornerShape(16.dp)),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("S", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 22.sp)
                }
                Spacer(modifier = Modifier.height(12.dp))
                Text("SILENT", fontWeight = FontWeight.Bold, fontSize = 16.sp, letterSpacing = 3.sp)
            }

            Spacer(modifier = Modifier.height(20.dp))

            VkLoginSection(
                vkReady = vkReady,
                vkUserId = vkUserId,
                bootstrapHash = bootstrapHash,
                vkMsg = vkMsg,
                onLinkVk = onLinkVk,
            )

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color(0xFFF3F4F6), RoundedCornerShape(12.dp))
                    .padding(4.dp),
            ) {
                listOf("login" to "Войти", "register" to "Регистрация").forEach { (key, label) ->
                    val selected = tab == key
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .background(
                                if (selected) Color.Black else Color.Transparent,
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
                                color = if (selected) Color.White else Color(0xFF6B7280),
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
                    Text("Подтвердите email", fontWeight = FontWeight.Medium, fontSize = 14.sp)
                    Text(
                        "Ссылка отправлена на $regEmail",
                        color = Color(0xFF6B7280),
                        fontSize = 12.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                    TextButton(onClick = {
                        tab = "login"
                        onRegDoneDismiss()
                    }) {
                        Text("Войти", fontSize = 12.sp, color = Color.Black)
                    }
                }
            } else {
                Text("Email", color = Color(0xFF6B7280), fontSize = 12.sp)
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("you@example.com", fontSize = 14.sp) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Color.Black,
                        unfocusedBorderColor = Color(0xFFE5E7EB),
                    ),
                )

                Spacer(modifier = Modifier.height(12.dp))

                Text("Пароль", color = Color(0xFF6B7280), fontSize = 12.sp)
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("••••••••", fontSize = 14.sp) },
                    singleLine = true,
                    visualTransformation = if (showPassword) VisualTransformation.None else PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Color.Black,
                        unfocusedBorderColor = Color(0xFFE5E7EB),
                    ),
                    trailingIcon = {
                        TextButton(onClick = { showPassword = !showPassword }) {
                            Text(
                                if (showPassword) "Скрыть" else "Показать",
                                fontSize = 11.sp,
                                color = Color(0xFF6B7280),
                            )
                        }
                    },
                )

                if (!error.isNullOrBlank()) {
                    Text(
                        error,
                        color = Color(0xFFEF4444),
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
                    colors = ButtonDefaults.buttonColors(containerColor = Color.Black),
                ) {
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = Color.White,
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

