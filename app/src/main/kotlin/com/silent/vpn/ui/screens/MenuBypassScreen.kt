package com.silent.vpn.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
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
import com.silent.vpn.service.OlcrtcVpnService
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.OlcrtcTunnelManager
import android.content.Context
import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** Как в 1.0.160: VK | olcrtc → Телемост | WB. Движок — olcrtc2. */
@Composable
fun MenuBypassScreen(
    repo: SilentRepository,
    fg: Color,
    vpnState: VpnState,
    @Suppress("UNUSED_PARAMETER")
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
    val switchLocked = applying || vpnState != VpnState.DISCONNECTED

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

    LaunchedEffect(vpnState) {
        if (vpnState != VpnState.DISCONNECTED) {
            pendingFamily = null
            pendingVk = null
            pendingOlc = null
            applyHint = "Отключите VPN перед сменой варианта обхода."
        }
    }

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

        applyHint?.let { hint ->
            Text(
                hint,
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }
        if (vpnState != VpnState.DISCONNECTED) {
            Text(
                "Переключение недоступно: VPN активен.",
                fontSize = 11.sp,
                color = fg.copy(alpha = 0.7f),
                modifier = Modifier.padding(bottom = 8.dp),
            )
        }

        BypassOption(
            title = "VK",
            selected = selFamily == SilentRepository.BYPASS_FAMILY_WDTT,
            enabled = !switchLocked,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_WDTT },
        )
        if (selFamily == SilentRepository.BYPASS_FAMILY_WDTT) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "VKCalls",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_VKCALLS,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_VKCALLS },
                )
                BypassOption(
                    title = "Авто капча",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_AUTO,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_AUTO },
                )
                BypassOption(
                    title = "Вручную",
                    selected = (pendingVk ?: vkMode) == SilentRepository.VK_CRED_MANUAL,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingVk = SilentRepository.VK_CRED_MANUAL },
                )
            }
        }

        BypassOption(
            title = "olcrtc",
            selected = selFamily == SilentRepository.BYPASS_FAMILY_OLCRTC2,
            enabled = !switchLocked,
            fg = fg,
            onSelect = { pendingFamily = SilentRepository.BYPASS_FAMILY_OLCRTC2 },
        )
        if (selFamily == SilentRepository.BYPASS_FAMILY_OLCRTC2) {
            Column(Modifier.padding(start = 12.dp)) {
                BypassOption(
                    title = "Яндекс Телемост",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_TELEMOST,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_TELEMOST },
                )
                BypassOption(
                    title = "WB Stream",
                    selected = (pendingOlc ?: olcProvider) == SilentRepository.OLCRTC_WBSTREAM,
                    enabled = !switchLocked,
                    fg = fg,
                    onSelect = { pendingOlc = SilentRepository.OLCRTC_WBSTREAM },
                )
            }
        }
    }

    if (hasPending && !switchLocked) {
        AlertDialog(
            onDismissRequest = {
                pendingFamily = null
                pendingVk = null
                pendingOlc = null
            },
            title = { Text("Применить?") },
            text = {
                Text(
                    bypassApplyLine(
                        family = family,
                        pendingFamily = pendingFamily,
                        vkMode = vkMode,
                        pendingVk = pendingVk,
                        olc = olcProvider,
                        pendingOlc = pendingOlc,
                        repo = repo,
                    ),
                )
            },
            confirmButton = {
                TvTextButton(onClick = {
                    val nextFam = pendingFamily
                    val nextVk = pendingVk
                    val nextOlc = pendingOlc
                    val prevOlc = olcProvider
                    pendingFamily = null
                    pendingVk = null
                    pendingOlc = null
                    applyHint = null
                    applying = true
                    scope.launch {
                        try {
                            applyBypassChoice(
                                context = context,
                                repo = repo,
                                family = family,
                                nextFam = nextFam,
                                nextVk = nextVk,
                                nextOlc = nextOlc,
                                onFamily = { family = it },
                                onVk = { vkMode = it },
                                onOlc = { olcProvider = it },
                                onHint = { applyHint = it },
                            )
                            scope.launch {
                                maybeRefreshOlcrtcSlotInBackground(
                                    repo = repo,
                                    switchedProvider = nextOlc != null && nextOlc != prevOlc,
                                    onEnsureOlcrtcApi = onEnsureOlcrtcApi,
                                    onHint = { applyHint = it },
                                )
                            }
                        } finally {
                            applying = false
                        }
                    }
                }) { Text("Применить", color = fg) }
            },
            dismissButton = {
                TvTextButton(onClick = {
                    pendingFamily = null
                    pendingVk = null
                    pendingOlc = null
                }) { Text("Отмена", color = fg.copy(0.6f)) }
            },
        )
    }
}

/** Как 1.0.160: «VK → olcrtc»; внутри семейства — провайдер или режим VK. */
private fun bypassApplyLine(
    family: String,
    pendingFamily: String?,
    vkMode: String,
    pendingVk: String?,
    olc: String,
    pendingOlc: String?,
    repo: SilentRepository,
): String {
    val nextFam = pendingFamily ?: family
    fun famName(f: String) =
        if (f == SilentRepository.BYPASS_FAMILY_OLCRTC2 || f == SilentRepository.BYPASS_FAMILY_OLCRTC) {
            "olcrtc"
        } else {
            "VK"
        }
    val from = famName(family)
    val to = famName(nextFam)
    if (from != to) return "$from → $to"
    val nextOlc = pendingOlc ?: olc
    if (nextFam == SilentRepository.BYPASS_FAMILY_OLCRTC2 && nextOlc != olc) {
        return "${repo.olcrtcProviderLabel(olc)} → ${repo.olcrtcProviderLabel(nextOlc)}"
    }
    val nextVk = pendingVk ?: vkMode
    if (nextFam == SilentRepository.BYPASS_FAMILY_WDTT && nextVk != vkMode) {
        return "${repo.vkCredStrategyLabel(vkMode)} → ${repo.vkCredStrategyLabel(nextVk)}"
    }
    return "$from → $to"
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

/**
 * Один путь смены канала: leave + hardReset leftover, затем DISCONNECT
 * только если VpnService ещё жив. Без fetch / «ждём конфиг» — слоты с login/VK.
 */
private suspend fun applyBypassChoice(
    context: Context,
    repo: SilentRepository,
    family: String,
    nextFam: String?,
    nextVk: String?,
    nextOlc: String?,
    onFamily: (String) -> Unit,
    onVk: (String) -> Unit,
    onOlc: (String) -> Unit,
    onHint: (String?) -> Unit,
) {
    val leftover =
        OlcrtcTunnelManager.running.value || OlcrtcTunnelManager.tunnelReady.value
    val running = SilentVpnService.isRunning || leftover
    nextFam?.let { fam ->
        if (
            OlcrtcSessionPolicy.shouldHardResetOlcrtcOnFamilyLeave(family, fam) || leftover
        ) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.APPLY,
                "stop leftover before family=$fam leftover=$leftover vpn=${SilentVpnService.isRunning}",
            )
            stopOlcrtcChannel(context, repo, repo.getOlcrtcProvider(), "apply_family_$fam")
        }
        repo.setBypassFamily(fam)
        onFamily(repo.getBypassFamily())
    }
    nextVk?.let {
        repo.setVkCredStrategy(it)
        onVk(it)
    }
    nextOlc?.let { nextProv ->
        val cur = repo.getOlcrtcProvider()
        if (
            OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply(
                pendingProvider = nextProv,
                currentProvider = cur,
                vpnOrTunnelRunning = running,
            ) || leftover
        ) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.APPLY,
                "stop leftover $cur → $nextProv leftover=$leftover vpn=${SilentVpnService.isRunning}",
            )
            stopOlcrtcChannel(context, repo, cur, "apply_switch $cur→$nextProv")
        }
        repo.setOlcrtcProvider(nextProv)
        onOlc(nextProv)
    }
    if (repo.getBypassFamily() != SilentRepository.BYPASS_FAMILY_OLCRTC2) {
        onHint("Выбрано: VK")
        return
    }
    val selected = repo.getOlcrtcProvider()
    val selectedRoom = repo.getCachedOlcrtcConfigForProvider(selected)
        ?.providers?.get(selected)?.room?.trim().orEmpty()
    val tm = repo.getCachedOlcrtcConfigForProvider(SilentRepository.OLCRTC_TELEMOST)
        ?.providers?.get(SilentRepository.OLCRTC_TELEMOST)?.room?.isNotBlank() == true
    val wb = repo.getCachedOlcrtcConfigForProvider(SilentRepository.OLCRTC_WBSTREAM)
        ?.providers?.get(SilentRepository.OLCRTC_WBSTREAM)?.room?.isNotBlank() == true
    com.silent.vpn.util.OlcrtcDiag.i(
        com.silent.vpn.util.OlcrtcDiag.APPLY,
        "cache-only $selected room=${selectedRoom.take(24)} tm=$tm wb=$wb",
    )
    onHint(
        if (selectedRoom.isNotBlank()) {
            "Готово: ${repo.olcrtcProviderLabel(selected)} · ${selectedRoom.take(28)}" +
                " (TM=${if (tm) "ok" else "—"} WB=${if (wb) "ok" else "—"})"
        } else {
            "Нет кеша ${repo.olcrtcProviderLabel(selected)}. Включите VK — конфиг подтянется сам."
        },
    )
}

private suspend fun maybeRefreshOlcrtcSlotInBackground(
    repo: SilentRepository,
    switchedProvider: Boolean,
    onEnsureOlcrtcApi: suspend (providers: Array<out String>) -> Boolean,
    onHint: (String?) -> Unit,
) {
    if (repo.getBypassFamily() != SilentRepository.BYPASS_FAMILY_OLCRTC2) return
    val provider = repo.getOlcrtcProvider()
    val need = repo.shouldRefreshOlcrtcSlot(provider, force = switchedProvider)
    if (!need) return
    onHint("Выбрано: ${repo.olcrtcProviderLabel(provider)} · обновляем слот…")
    val ok = withTimeoutOrNull(22_000L) {
        onEnsureOlcrtcApi(arrayOf(provider))
    } == true
    val room = repo.getCachedOlcrtcConfigForProvider(provider)
        ?.providers?.get(provider)?.room?.trim().orEmpty()
    val ageSec = (repo.getOlcrtcCacheAgeMs(provider) ?: 0L) / 1000L
    onHint(
        if (ok && room.isNotBlank()) {
            "Обновлено: ${repo.olcrtcProviderLabel(provider)} · ${room.take(28)} (age ${ageSec}s)"
        } else {
            "Оставлен кеш: ${repo.olcrtcProviderLabel(provider)}" +
                if (room.isNotBlank()) " · ${room.take(28)}" else " · нет room"
        },
    )
}

/**
 * Leave + native/hev reset. DISCONNECT через startService (не FGS) и только
 * если VpnService ещё жив — иначе вылет на переходе к VK.
 */
private suspend fun stopOlcrtcChannel(
    context: Context,
    repo: SilentRepository,
    provider: String,
    reason: String,
) {
    val roomId = repo.sessionOlcrtcRoomDbId()
        ?: repo.getCachedOlcrtcConfigForProvider(provider)
            ?.providers?.get(provider)?.room_db_id
    runCatching { repo.leaveOlcrtcRoom(provider = provider, roomDbId = roomId) }
    OlcrtcTunnelManager.hardReset(reason)
    OlcrtcVpnService.suppressDestroyStop = false
    runCatching {
        context.startService(
            Intent(context, OlcrtcVpnService::class.java).apply {
                action = OlcrtcVpnService.ACTION_STOP
            },
        )
    }
    delay(250)
    // Native уже снесён. Не поднимать мёртвый VpnService ради DISCONNECT — вылет FGS.
    if (SilentVpnService.isRunning) {
        runCatching {
            context.startService(
                Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_DISCONNECT
                },
            )
        }
        var waited = 0
        while (
            waited < 30 &&
            (
                SilentVpnService.isRunning ||
                    OlcrtcTunnelManager.running.value ||
                    OlcrtcTunnelManager.tunnelReady.value
            )
        ) {
            delay(200)
            waited++
        }
        OlcrtcTunnelManager.hardReset("${reason}_after_stop")
        delay(300)
    }
    repo.clearOlcrtcSessionBind()
}
