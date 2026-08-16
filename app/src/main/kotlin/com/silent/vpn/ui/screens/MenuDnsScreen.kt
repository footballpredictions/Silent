package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.theme.ThemePalette
import com.silent.vpn.ui.theme.themeTextFieldColors
import com.silent.vpn.ui.tv.TvPrimaryButton
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import com.silent.vpn.util.rememberIsTv

@Composable
fun MenuDnsScreen(
    repo: SilentRepository,
    palette: ThemePalette,
    onBack: () -> Unit,
) {
    val fg = palette.fg
    val fieldColors = themeTextFieldColors(palette)

    var preset by remember { mutableStateOf(repo.getDnsPreset()) }
    var customInput by remember { mutableStateOf(repo.getCustomDnsRaw()) }
    var pending by remember { mutableStateOf<DnsPreset?>(null) }

    val locked = SilentVpnService.isRunning
    val customServers = DnsPreset.sanitizeCustomServers(customInput)
    val customTouched = customInput.isNotBlank()

    Column(
        Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        TvTextButton(
            onClick = onBack,
            modifier = Modifier.padding(bottom = 16.dp),
            requestFocusOnOpen = true,
            requestFocusKey = "dns",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }

        Text(
            "DNS",
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
            modifier = Modifier.padding(bottom = 4.dp),
        )
        Text(
            "Используйте рекомендуемый DNS или укажите свой. " +
                "Применяется при следующем подключении VPN.",
            fontSize = 11.sp,
            color = fg.copy(alpha = 0.45f),
            modifier = Modifier.padding(bottom = 16.dp),
        )

        if (locked) {
            Text(
                "Отключите VPN перед сменой DNS.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.45f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        DnsPreset.selectable().forEach { option ->
            DnsOptionRow(
                title = option.title,
                subtitle = option.subtitle,
                selected = preset == option,
                enabled = !locked,
                fg = fg,
                onSelect = { pending = option },
            )
        }

        HorizontalDivider(
            color = palette.divider,
            modifier = Modifier.padding(vertical = 12.dp),
        )

        DnsOptionRow(
            title = DnsPreset.CUSTOM.title,
            subtitle = customServers ?: DnsPreset.CUSTOM.subtitle,
            selected = preset == DnsPreset.CUSTOM,
            enabled = !locked && customServers != null,
            fg = fg,
            onSelect = { pending = DnsPreset.CUSTOM },
        )

        OutlinedTextField(
            value = customInput,
            onValueChange = { customInput = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 4.dp),
            placeholder = {
                Text("1.1.1.1, 8.8.8.8", fontSize = 13.sp, color = palette.fieldPlaceholder)
            },
            singleLine = true,
            shape = RoundedCornerShape(12.dp),
            colors = fieldColors,
            enabled = !locked,
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Done,
            ),
        )
        Text(
            when {
                customTouched && customServers == null ->
                    "Нужны IP-адреса, например 1.1.1.1 или 2606:4700:4700::1111"
                else ->
                    "IPv4 или IPv6, до ${DnsPreset.MAX_CUSTOM_SERVERS} адресов через запятую"
            },
            fontSize = 11.sp,
            color = if (customTouched && customServers == null) {
                palette.red
            } else {
                fg.copy(alpha = 0.45f)
            },
            modifier = Modifier.padding(top = 6.dp),
        )
        TvPrimaryButton(
            onClick = { pending = DnsPreset.CUSTOM },
            enabled = !locked && customServers != null && customServers != repo.getCustomDnsRaw().ifBlank { null },
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp, bottom = 8.dp),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = palette.primaryBtnBg,
                contentColor = palette.primaryBtnFg,
                disabledContainerColor = palette.primaryBtnBg.copy(alpha = 0.4f),
                disabledContentColor = palette.primaryBtnFg.copy(alpha = 0.5f),
            ),
        ) {
            Text("Использовать свой DNS", fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        }
    }

    pending?.let { next ->
        val nextServers = if (next == DnsPreset.CUSTOM) customServers else next.servers
        if (next == DnsPreset.CUSTOM && nextServers == null) {
            pending = null
            return@let
        }
        if (next == preset && next != DnsPreset.CUSTOM) {
            pending = null
            return@let
        }
        AlertDialog(
            onDismissRequest = { pending = null },
            title = { Text("Сменить DNS?") },
            text = {
                Text(
                    buildString {
                        append("Было: ")
                        append(repo.dnsDescription())
                        append("\nБудет: ")
                        append(next.title)
                        if (!nextServers.isNullOrBlank()) append(" ($nextServers)")
                        append("\n\nПереподключите VPN, чтобы применить.")
                    },
                )
            },
            confirmButton = {
                TvTextButton(
                    onClick = {
                        if (next == DnsPreset.CUSTOM) {
                            repo.setCustomDns(customInput)?.let { customInput = it }
                        }
                        repo.setDnsPreset(next)
                        preset = next
                        pending = null
                    },
                ) { Text("Применить") }
            },
            dismissButton = {
                TvTextButton(onClick = { pending = null }) { Text("Отмена") }
            },
        )
    }
}

@Composable
private fun DnsOptionRow(
    title: String,
    subtitle: String,
    selected: Boolean,
    enabled: Boolean,
    fg: Color,
    onSelect: () -> Unit,
) {
    val isTv = rememberIsTv()
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(
                if (isTv && enabled) {
                    Modifier.tvClickable(enabled = enabled, onClick = onSelect)
                } else {
                    Modifier
                },
            )
            .padding(vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        RadioButton(
            selected = selected,
            onClick = { if (enabled && !isTv) onSelect() },
            enabled = enabled && !isTv,
        )
        Column(Modifier.padding(start = 4.dp, top = 12.dp)) {
            Text(title, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = fg.copy(if (enabled) 1f else 0.45f))
            Text(subtitle, fontSize = 12.sp, color = fg.copy(if (enabled) 0.6f else 0.35f))
        }
    }
}
