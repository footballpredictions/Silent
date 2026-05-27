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
        "Вставьте ссылку vk.com/call/join/… или хеш, затем подключитесь. Хеш сохранится автоматически.",
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
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Go),
        keyboardActions = KeyboardActions(onGo = { if (!bootstrapConnecting) onConnect(input) }),
        shape = RoundedCornerShape(12.dp),
        colors = fieldColors,
    )

    Spacer(modifier = Modifier.height(10.dp))

    Button(
        onClick = { onConnect(input) },
        enabled = input.isNotBlank() && !bootstrapConnecting,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = Color.White,
            contentColor = Color.Black,
            disabledContainerColor = Color(0xFF333333),
            disabledContentColor = Color(0xFF666666),
        ),
    ) {
        Text(
            if (bootstrapConnecting) "Подключение…" else "Подключить для входа",
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
        )
    }

    if (statusMsg.isNotBlank()) {
        Text(
            statusMsg,
            fontSize = 11.sp,
            color = AuthColors.hint,
            modifier = Modifier.padding(top = 8.dp),
        )
    }

    Spacer(modifier = Modifier.height(16.dp))
    HorizontalDivider(color = AuthColors.divider)
    Spacer(modifier = Modifier.height(16.dp))
}
