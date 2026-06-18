package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun VkLoginSection(
    vkReady: Boolean,
    vkUserId: Long?,
    bootstrapHash: String?,
    vkMsg: String,
    onLinkVk: () -> Unit,
) {
    Text(
        "Шаг 1 — VK",
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        color = Color.Black,
    )
    Text(
        when {
            vkReady && vkUserId != null -> "VK готов (ID $vkUserId). Можно войти в аккаунт."
            else -> "Привяжите VK — откроется вход (логин и пароль). Если предложат «в один клик» — выберите «Ввести вручную»"
        },
        fontSize = 11.sp,
        color = Color(0xFF6B7280),
        modifier = Modifier.padding(top = 6.dp),
    )
    bootstrapHash?.takeIf { it.isNotBlank() }?.let { hash ->
        Text(
            "Хеш: ${hash.take(16)}…",
            fontSize = 10.sp,
            color = Color(0xFF4680C2),
            modifier = Modifier.padding(top = 4.dp),
        )
    }

    Button(
        onClick = onLinkVk,
        enabled = !vkReady,
        colors = ButtonDefaults.buttonColors(
            containerColor = Color(0xFF4680C2),
            contentColor = Color.White,
            disabledContainerColor = Color(0xFF4680C2).copy(alpha = 0.35f),
        ),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
    ) {
        Text(
            if (vkReady) "VK подключён" else "Привязать VK ID",
            fontSize = 12.sp,
        )
    }

    if (vkMsg.isNotBlank()) {
        Text(
            vkMsg,
            fontSize = 11.sp,
            color = Color(0xFF6B7280),
            modifier = Modifier.padding(top = 8.dp),
        )
    }

    Spacer(modifier = Modifier.height(16.dp))
    HorizontalDivider(color = Color(0xFFE5E7EB))
    Spacer(modifier = Modifier.height(16.dp))
    Text(
        "Шаг 2 — вход в Silent VPN",
        fontWeight = FontWeight.SemiBold,
        fontSize = 13.sp,
        color = Color.Black,
    )
    Spacer(modifier = Modifier.height(8.dp))
}
