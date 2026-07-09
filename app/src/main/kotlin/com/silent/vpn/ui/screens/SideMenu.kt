package com.silent.vpn.ui.screens

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForwardIos
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.sessionsBadge
import com.silent.vpn.ui.theme.AppearanceMode
import com.silent.vpn.ui.theme.resolveThemePalette
import com.silent.vpn.ui.theme.parseColor

@Composable
fun SideMenuContent(
    profile: UserProfile?,
    theme: ThemeData?,
    appearanceMode: AppearanceMode = AppearanceMode.LIGHT,
    sessionDeviceId: String? = null,
    onClose: () -> Unit,
    onSubscription: () -> Unit,
    onSettings: () -> Unit,
    onPromo: () -> Unit,
    onDevices: () -> Unit,
    onSupport: () -> Unit,
    onAbout: () -> Unit,
    onLogout: () -> Unit,
) {
    val palette = theme.resolveThemePalette(appearanceMode)
    val bg = palette.surface
    val fg = palette.fg
    val edge = if (palette.dark) Color(0xFF52525B) else palette.borderStrong

    Column(
        modifier = Modifier
            .fillMaxHeight()
            .width(280.dp)
            .background(bg)
            .border(1.dp, edge)
            .verticalScroll(rememberScrollState()),
    ) {
        // Header
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .background(fg)
                .padding(20.dp),
        ) {
            Column {
                Spacer(modifier = Modifier.height(32.dp))
                Text(
                    profile?.email ?: "—",
                    color = bg,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Text(
                    "Аккаунт: ${profile?.display_id ?: "—"}",
                    color = bg.copy(alpha = 0.6f),
                    fontSize = 12.sp,
                    modifier = Modifier.padding(top = 2.dp),
                )
                sessionDeviceId?.takeIf { it.isNotBlank() }?.let { sid ->
                    Text(
                        "Сессия: ${sid.take(8).uppercase()}",
                        color = bg.copy(alpha = 0.45f),
                        fontSize = 11.sp,
                        modifier = Modifier.padding(top = 2.dp),
                    )
                }
            }
            IconButton(onClick = onClose, modifier = Modifier.align(Alignment.TopEnd)) {
                Icon(Icons.Default.Close, contentDescription = null, tint = bg)
            }
        }

        Spacer(modifier = Modifier.height(8.dp))

        val items = listOf(
            Triple("Подписка", onSubscription, when {
                profile?.subscription?.plan_type == "test" -> "Тест"
                profile?.is_admin == true || profile?.subscription?.plan_type == "unlimited" -> "Бессрочно"
                profile?.subscription?.is_active == true && profile.subscription.plan_type == "trial" -> "Пробный"
                profile?.subscription?.is_active == true -> "Активна"
                else -> "Нет"
            }),
            Triple("Настройки", onSettings, null),
            Triple("Промокоды", onPromo, null),
            Triple("Сессии", onDevices, profile?.sessionsBadge() ?: "0/3"),
            Triple("Поддержка", onSupport, null),
            Triple("О сервисе", onAbout, null),
        )

        items.forEach { (label, action, badge) ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable(onClick = action)
                    .padding(horizontal = 20.dp, vertical = 14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, color = fg, fontSize = 14.sp, modifier = Modifier.weight(1f))
                if (badge != null) {
                    Text(badge, color = fg.copy(alpha = 0.4f), fontSize = 12.sp)
                    Spacer(modifier = Modifier.width(6.dp))
                }
                Icon(
                    Icons.AutoMirrored.Filled.ArrowForwardIos,
                    contentDescription = null,
                    tint = fg.copy(alpha = 0.3f),
                    modifier = Modifier.size(12.dp),
                )
            }
            Divider(color = fg.copy(alpha = 0.06f), thickness = 0.5.dp)
        }

        Spacer(modifier = Modifier.weight(1f))
        Spacer(modifier = Modifier.height(16.dp))

        TextButton(
            onClick = onLogout,
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp, vertical = 8.dp),
        ) {
            Text("Выйти", color = Color(0xFFEF4444), fontSize = 14.sp, fontWeight = FontWeight.Medium)
        }

        Spacer(modifier = Modifier.height(24.dp))
    }
}
