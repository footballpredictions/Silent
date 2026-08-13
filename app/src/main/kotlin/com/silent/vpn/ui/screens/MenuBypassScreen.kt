package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.RadioButton
import androidx.compose.material3.RadioButtonDefaults
import androidx.compose.material3.Text
import com.silent.vpn.ui.tv.TvTextButton
import com.silent.vpn.ui.tv.tvClickable
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.silent.vpn.BuildConfig
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.policy.OlcrtcSessionPolicy
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.OlcrtcTunnelManager
import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Как в 1.0.160: VK | olcrtc → Телемост | WB. Движок — olcrtc2. */
@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    onEnsureOlcrtcApi: suspend (providers: Array<out String>) -> Boolean = { true },
    onBack: () -> Unit,
) {
    var family by remember { mutableStateOf(repo.getBypassFamily()) }
    var vkMode by remember { mutableStateOf(repo.getVkCredStrategy()) }
    var olcProvider by remember { mutableStateOf(repo.getOlcrtcProvider()) }
    var pendingFamily by remember { mutableStateOf<String?>(null) }
    var pendingVk by remember { mutableStateOf<String?>(null) }
    var pendingOlc by remember { mutableStateOf<String?>(null) }
    var applying by remember { mutableStateOf(false) }
    var applyHint by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    val vpnRunning = SilentVpnService.isRunning

    LaunchedEffect(Unit) {
        if (!BuildConfig.DEBUG) {
            repo.setBypassFamily(SilentRepository.BYPASS_FAMILY_WDTT)
        }
        // Конфиг TM/WB — только login / синхронизация при VK, не при открытии меню.
    }

    val selFamily = pendingFamily ?: family
    val hasPending =
        (pendingFamily != null && pendingFamily != family) ||
            (pendingVk != null && pendingVk != vkMode) ||
            (pendingOlc != null && pendingOlc != olcProvider)

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
            requestFocusKey = "bypass",
        ) {
            Text("← Назад", fontSize = 12.sp, color = fg.copy(alpha = 0.4f))
        }

        Text(
            "Варианты обхода",
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
            color = fg,
            modifier = Modifier.padding(bottom = 12.dp),
        )

        if (!BuildConfig.DEBUG) {
            Text(
                "Только VK / WDTT. olcrtc — в debug-сборке.",
                fontSize = 12.sp,
                color = fg.copy(alpha = 0.55f),
            )
            return@Column
        }

        if (vpnRunning) {
            Text(
                "Отключите VPN перед сменой варианта.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.45f),
                modifier = Modifier.padding(bottom = 12.dp),
            )
        }

        applyHint?.let { hint ->
            Text(
                hint,
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        BypassOption(
            title = "VK",
            selected = selFamily == SilentRepository.BYPASS_FAMILY_WDTT,
            enabled = !vpnRunning && !applying,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_WDTT },
        )
        if (selFamily == SilentRepository.BYPASS_FAMILY_WDTT) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "VKCalls",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_VKCALLS,
                    enabled = !vpnRunning && !applying,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_VKCALLS },
                )
                BypassOption(
                    title = "Авто капча",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_AUTO,
                    enabled = !vpnRunning && !applying,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_AUTO },
                )
                BypassOption(
                    title = "Вручную",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_MANUAL,
                    enabled = !vpnRunning && !applying,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_MANUAL },
                )
            }
        }

        BypassOption(
            title = "olcrtc",
            selected = selFamily == SilentRepository.BYPASS_FAMILY_OLCRTC2,
            enabled = !vpnRunning && !applying,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_OLCRTC2 },
        )
        if (selFamily == SilentRepository.BYPASS_FAMILY_OLCRTC2) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "Яндекс Телемост",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_TELEMOST,
                    enabled = !vpnRunning && !applying,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_TELEMOST },
                )
                BypassOption(
                    title = "WB Stream",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_WBSTREAM,
                    enabled = !vpnRunning && !applying,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_WBSTREAM },
                )
            }
        }
    }

    if (hasPending || applying) {
        AlertDialog(
            onDismissRequest = {
                if (applying) return@AlertDialog
                pendingFamily = null
                pendingVk = null
                pendingOlc = null
            },
            title = { Text(if (applying) "Получение сессии…" else "Применить?") },
            text = {
                if (applying) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp,
                            color = fg,
                        )
                        Spacer(Modifier.width(10.dp))
                        Text(
                            "Ждём конфиг канала…",
                            color = fg.copy(0.8f),
                            fontSize = 12.sp,
                        )
                    }
                } else {
                    Text(
                        repo.bypassFamilyLabel(family) +
                            (pendingFamily?.let { " → ${repo.bypassFamilyLabel(it)}" } ?: ""),
                    )
                }
            },
            confirmButton = {
                if (!applying) {
                    TvTextButton(onClick = {
                        applying = true
                        applyHint = null
                        scope.launch {
                            try {
                                pendingFamily?.let {
                                    repo.setBypassFamily(it)
                                    family = repo.getBypassFamily()
                                }
                                pendingVk?.let {
                                    repo.setVkCredStrategy(it)
                                    vkMode = it
                                }
                                pendingOlc?.let { nextProv ->
                                    val cur = repo.getOlcrtcProvider()
                                    val running =
                                        SilentVpnService.isRunning || OlcrtcTunnelManager.running.value
                                    if (OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply(
                                            pendingProvider = nextProv,
                                            currentProvider = cur,
                                            vpnOrTunnelRunning = running,
                                        )
                                    ) {
                                        // Сначала стоп старого канала. Leave только по cur (не prefs после set).
                                        // Не clearSessionBind до leave — иначе ViewModel late-leave уйдёт в prefs=new.
                                        com.silent.vpn.util.OlcrtcDiag.w(
                                            com.silent.vpn.util.OlcrtcDiag.APPLY,
                                            "stop before switch $cur → $nextProv running=$running",
                                        )
                                        val roomId = repo.sessionOlcrtcRoomDbId()
                                            ?: repo.getCachedOlcrtcConfigForProvider(cur)
                                                ?.providers?.get(cur)?.room_db_id
                                        runCatching {
                                            repo.leaveOlcrtcRoom(provider = cur, roomDbId = roomId)
                                        }
                                        // Как kill app: снести hev/native до DISCONNECT.
                                        com.silent.vpn.vpn.OlcrtcTunnelManager.hardReset(
                                            "apply_switch $cur→$nextProv",
                                        )
                                        runCatching {
                                            val intent = Intent(
                                                context,
                                                SilentVpnService::class.java,
                                            ).apply {
                                                action = SilentVpnService.ACTION_DISCONNECT
                                            }
                                            ContextCompat.startForegroundService(context, intent)
                                        }
                                        repeat(30) {
                                            if (!SilentVpnService.isRunning &&
                                                !OlcrtcTunnelManager.running.value &&
                                                !OlcrtcTunnelManager.tunnelReady.value
                                            ) {
                                                return@repeat
                                            }
                                            delay(200)
                                        }
                                        com.silent.vpn.vpn.OlcrtcTunnelManager.hardReset(
                                            "apply_after_stop",
                                        )
                                        delay(300)
                                        repo.clearOlcrtcSessionBind()
                                        applyHint = "Старый канал остановлен → $nextProv"
                                    }
                                    com.silent.vpn.util.OlcrtcDiag.i(
                                        com.silent.vpn.util.OlcrtcDiag.APPLY,
                                        "apply provider=$nextProv",
                                    )
                                    repo.setOlcrtcProvider(nextProv)
                                    olcProvider = nextProv
                                }
                                if (repo.getBypassFamily() == SilentRepository.BYPASS_FAMILY_OLCRTC2) {
                                    // Только dual-cache: без сети при TM↔WB. Fetch — login / VK sync.
                                    val selected = repo.getOlcrtcProvider()
                                    val selectedRoom = repo.getCachedOlcrtcConfigForProvider(selected)
                                        ?.providers?.get(selected)?.room?.trim().orEmpty()
                                    com.silent.vpn.util.OlcrtcDiag.i(
                                        com.silent.vpn.util.OlcrtcDiag.APPLY,
                                        "swap cache-only $selected room=${selectedRoom.take(24)}",
                                    )
                                    val tm = repo.getCachedOlcrtcConfigForProvider(
                                        SilentRepository.OLCRTC_TELEMOST,
                                    ) != null
                                    val wb = repo.getCachedOlcrtcConfigForProvider(
                                        SilentRepository.OLCRTC_WBSTREAM,
                                    ) != null
                                    applyHint = when {
                                        selectedRoom.isNotBlank() ->
                                            "Готово: ${repo.olcrtcProviderLabel(selected)} · ${selectedRoom.take(28)}" +
                                                " (TM=${if (tm) "ok" else "—"} WB=${if (wb) "ok" else "—"})"
                                        else ->
                                            "Нет кеша для ${repo.olcrtcProviderLabel(selected)}. " +
                                                "Войдите снова или включите VK и синхронизацию."
                                    }
                                }
                            } finally {
                                pendingFamily = null
                                pendingVk = null
                                pendingOlc = null
                                applying = false
                            }
                        }
                    }) { Text("Применить", color = fg) }
                }
            },
            dismissButton = {
                if (!applying) {
                    TvTextButton(onClick = {
                        pendingFamily = null
                        pendingVk = null
                        pendingOlc = null
                    }) { Text("Отмена", color = fg.copy(0.6f)) }
                }
            },
        )
    }
}

@Composable
private fun BypassOption(
    title: String,
    selected: Boolean,
    enabled: Boolean,
    fg: Color,
    onSelect: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .tvClickable(enabled = enabled, onClick = onSelect)
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(
            selected = selected,
            onClick = { if (enabled) onSelect() },
            enabled = enabled,
            colors = RadioButtonDefaults.colors(
                selectedColor = fg,
                unselectedColor = fg.copy(alpha = 0.4f),
            ),
        )
        Text(
            title,
            fontSize = 14.sp,
            color = if (enabled) fg else fg.copy(alpha = 0.4f),
            modifier = Modifier.padding(start = 4.dp),
        )
    }
}
