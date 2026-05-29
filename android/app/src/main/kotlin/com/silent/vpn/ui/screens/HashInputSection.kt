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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
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

@Composable
fun HashInputSection(
    bootstrapHash: String?,
    statusMsg: String,
    bootstrapConnecting: Boolean,
    bootstrapReady: Boolean,
    onConnect: (String) -> Unit,
) {
    var input by remember(bootstrapHash) { mutableStateOf(bootstrapHash.orEmpty()) }
    val fieldColors = authTextFieldColors()

    Text(
        "Шаг 1 — хеш звонка VK",
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        color = Color.White,
    )
    Text(
        "Временный интернет на 2 минуты — только для входа или регистрации. По истечении хеш сбросится.",
        fontSize = 11.sp,
        color = AuthColors.hint,
        modifier = Modifier.padding(top = 4.dp, bottom = 8.dp),
    )

    OutlinedTextField(
        value = input,
        onValueChange = { input = it },
        modifier = Modifier.fillMaxWidth(),
        placeholder = {
            Text("Хеш или ссылка на звонок VK", fontSize = 13.sp, color = AuthColors.fieldPlaceholder)
        },
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
        else -> "Подключить для входа"
    }
    val buttonEnabled = input.isNotBlank() && !bootstrapConnecting && !bootstrapReady

    Button(
        onClick = { onConnect(input) },
        enabled = buttonEnabled,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = when {
                bootstrapReady -> Color(0xFF16A34A)
                else -> Color.White
            },
            contentColor = if (bootstrapReady) Color.White else Color.Black,
            disabledContainerColor = if (bootstrapReady) Color(0xFF16A34A) else Color(0xFF333333),
            disabledContentColor = if (bootstrapReady) Color.White else Color(0xFF666666),
        ),
    ) {
        Text(buttonText, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }

    if (statusMsg.isNotBlank()) {
        val statusColor = when {
            bootstrapReady -> Color(0xFF16A34A)
            statusMsg.contains("ошиб", ignoreCase = true) ||
                statusMsg.contains("не удалось", ignoreCase = true) ||
                statusMsg.contains("невер", ignoreCase = true) -> Color(0xFFEF4444)
            bootstrapConnecting -> Color(0xFF6B7280)
            else -> Color(0xFF6B7280)
        }
        Text(
            statusMsg,
            fontSize = 11.sp,
            color = statusColor,
            modifier = Modifier.padding(top = 8.dp),
        )
    }

    Spacer(modifier = Modifier.height(16.dp))
    HorizontalDivider(color = AuthColors.divider)
    Spacer(modifier = Modifier.height(16.dp))
}
