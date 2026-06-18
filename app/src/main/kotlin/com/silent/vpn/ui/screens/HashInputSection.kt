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
import com.silent.vpn.vk.HashParser

@Composable
fun HashInputSection(
    ui: LoginUi,
    theme: ThemeData?,
    bootstrapHash: String?,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    bootstrapSecondsLeft: Int? = null,
    onConnect: (String) -> Unit,
    onContinueToAuth: () -> Unit = {},
    onOpenVkLink: () -> Unit,
    showDivider: Boolean = true,
) {
    var input by remember(bootstrapHash) { mutableStateOf(bootstrapHash.orEmpty()) }
    val fieldColors = loginTextFieldColors(ui)

    val title = theme?.login_step1_title ?: ThemeData().login_step1_title
    val hint = theme?.login_step1_instruction ?: ThemeData().login_step1_instruction
    val placeholder = theme?.login_hash_placeholder ?: ThemeData().login_hash_placeholder
    val confirmBtn = theme?.login_hash_button_text ?: ThemeData().login_hash_button_text
    val vkLabel = theme?.login_vk_mobile_link_text ?: ThemeData().login_vk_mobile_link_text

    val showCountdown = bootstrapReady

    val savedHash = bootstrapHash?.trim().orEmpty()
    val enteredHash = HashParser.extract(input)?.trim().orEmpty()
    val hashChanged = bootstrapReady && enteredHash.isNotBlank() && enteredHash != savedHash

    Text(title, fontWeight = FontWeight.SemiBold, fontSize = 13.sp, color = ui.fg)
    if (showCountdown) {
        val sec = bootstrapSecondsLeft
        val countdownText = when {
            sec != null -> statusMsg.ifBlank { "Канал готов. Осталось %d:%02d".format(sec / 60, sec % 60) }
            statusMsg.isNotBlank() -> statusMsg
            else -> "VPN включён — можно продолжить"
        }
        Text(
            countdownText,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            color = ui.green,
            modifier = Modifier.padding(top = 6.dp, bottom = 8.dp),
        )
    } else {
        Text(hint, fontSize = 11.sp, color = ui.hint, modifier = Modifier.padding(top = 4.dp, bottom = 8.dp))
    }
    TextButton(onClick = onOpenVkLink, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
        Text(vkLabel, fontSize = 11.sp, color = ui.linkColor, textDecoration = androidx.compose.ui.text.style.TextDecoration.Underline)
    }

    OutlinedTextField(
        value = input,
        onValueChange = { input = it },
        modifier = Modifier.fillMaxWidth(),
        placeholder = { Text(placeholder, fontSize = 13.sp, color = ui.fieldPlaceholder) },
        singleLine = true,
        enabled = !bootstrapReady || hashChanged,
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
        keyboardActions = KeyboardActions(onGo = {
            when {
                bootstrapConnecting -> Unit
                bootstrapReady && !hashChanged -> onContinueToAuth()
                else -> onConnect(input)
            }
        }),
        shape = RoundedCornerShape(12.dp),
        colors = fieldColors,
    )

    Spacer(modifier = Modifier.height(10.dp))

    val buttonText = when {
        bootstrapConnecting -> "Подключение…"
        bootstrapReady && hashChanged -> "Переподключить"
        bootstrapReady && bootstrapSecondsLeft != null -> {
            val sec = bootstrapSecondsLeft ?: 0
            "К шагу 2 · %d:%02d".format(sec / 60, sec % 60)
        }
        bootstrapReady -> "К шагу 2 ✓"
        else -> confirmBtn
    }
    val buttonEnabled = when {
        bootstrapConnecting -> false
        bootstrapReady && !hashChanged -> true
        else -> input.isNotBlank()
    }

    Button(
        onClick = {
            if (bootstrapReady && !hashChanged) onContinueToAuth()
            else onConnect(input)
        },
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

    if (statusMsg.isNotBlank() && !showCountdown) {
        val statusColor = when {
            bootstrapReady && bootstrapSecondsLeft == null -> ui.green
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
