package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData
import com.silent.vpn.ui.theme.LoginUi
import com.silent.vpn.ui.theme.loginTextFieldColors

@Composable
fun HashInputSection(
    ui: LoginUi,
    theme: ThemeData?,
    bootstrapHash: String?,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    onConnect: (String) -> Unit,
    onOpenVkLink: () -> Unit,
    showDivider: Boolean = true,
) {
    var input by remember(bootstrapHash) { mutableStateOf(bootstrapHash.orEmpty()) }
    val fieldColors = loginTextFieldColors(ui)

    val title = theme?.login_step1_title ?: "Шаг 1 — хеш звонка VK"
    val hint = theme?.login_step1_instruction
        ?: "Временный интернет на 2 минуты — только для входа или регистрации."
    val placeholder = theme?.login_hash_placeholder ?: "Хеш или ссылка на звонок VK"
    val confirmBtn = theme?.login_hash_button_text ?: "Подтвердить"
    val vkLabel = theme?.login_vk_mobile_link_text ?: "ВКонтакте — раздел «Звонки»"

    Text(title, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = ui.fg)
    Text(hint, fontSize = 11.sp, color = ui.hint, modifier = Modifier.padding(top = 4.dp, bottom = 8.dp))
    TextButton(onClick = onOpenVkLink, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
        Text(vkLabel, fontSize = 11.sp, color = ui.linkColor, textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline)
    }

    OutlinedTextField(
        value = input,
        onValueChange = { input = it },
        modifier = Modifier.fillMaxWidth(),
        placeholder = { Text(placeholder, fontSize = 13.sp, color = ui.fieldPlaceholder) },
        singleLine = true,
        enabled = !bootstrapReady,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
        keyboardActions = KeyboardActions(onGo = { if (!bootstrapConnecting && !bootstrapReady) onConnect(input) }),
        shape = RoundedCornerShape(12.dp),
        colors = fieldColors,
    )

    Spacer(modifier = Modifier.height(10.dp))

    val buttonText = when {
        bootstrapConnecting -> "Подключение…"
        bootstrapReady -> "Подключено ✓"
        else -> confirmBtn
    }
    val buttonEnabled = input.isNotBlank() && !bootstrapConnecting && !bootstrapReady

    Button(
        onClick = { onConnect(input) },
        enabled = buttonEnabled,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = if (bootstrapReady) ui.green else ui.primaryBtnBg,
            contentColor = if (bootstrapReady) Color.White else ui.primaryBtnFg,
            disabledContainerColor = if (bootstrapReady) ui.green else ui.primaryBtnBg.copy(alpha = 0.4f),
            disabledContentColor = if (bootstrapReady) Color.White else ui.primaryBtnFg.copy(alpha = 0.5f),
        ),
    ) {
        Text(buttonText, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }

    if (statusMsg.isNotBlank()) {
        val statusColor = when {
            bootstrapReady -> ui.green
            statusMsg.contains("ошиб", ignoreCase = true) ||
                statusMsg.contains("не удалось", ignoreCase = true) ||
                statusMsg.contains("невер", ignoreCase = true) ||
                statusMsg.contains("истекло", ignoreCase = true) -> ui.red
            statusMsg.contains("канал готов", ignoreCase = true) ||
                statusMsg.contains("осталось", ignoreCase = true) -> ui.green
            bootstrapConnecting -> ui.hint
            else -> ui.hint
        }
        Text(statusMsg, fontSize = 11.sp, color = statusColor, modifier = Modifier.padding(top = 8.dp))
    }

    if (showDivider) {
        Spacer(modifier = Modifier.height(16.dp))
    }
}
