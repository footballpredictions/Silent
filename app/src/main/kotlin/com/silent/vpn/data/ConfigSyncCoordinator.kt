package com.silent.vpn.data

import android.content.Context
import android.util.Log
import com.silent.vpn.policy.ConfigSyncSkipPolicy
import com.silent.vpn.sync.MobileSyncLog
import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Канал обновлений: sync-state → profile, hashes, theme, подписка.
 * Wi‑Fi — public API; LTE + VPN — приложение в туннеле, прямой 10.66.66.1 (без overlay).
 * Подписка сверяется каждые 2 мин (rev не растёт при revoke/истечении).
 */
object ConfigSyncCoordinator {
    private const val TAG = "ConfigSync"
    /** Единый интервал фонового sync (хеши/тема/профиль/подписка). */
    private const val POLL_MS = 60 * 60 * 1000L
    /** Wi‑Fi: rev профиля не растёт при истечении expires_at — отдельная сверка подписки. */
    private const val WIFI_SUBSCRIPTION_CHECK_MS = 2 * 60 * 1000L
    private const val START_DELAY_MS = 5_000L

    private val tickMutex = Mutex()
    private var pollJob: Job? = null
    private var wifiSubscriptionJob: Job? = null

    interface Listener {
        fun onTheme(theme: ThemeData)
        fun onProfile(profile: UserProfile)
        fun onHashesUpdated(items: List<HashItemDto>, applyToTunnel: Boolean)
        fun onWifiSyncTickStart()
        fun isPollAllowed(): Boolean
        /** Wi‑Fi: подписка через public API — VPN не нужен. */
        fun isWifiSubscriptionPollAllowed(): Boolean
        fun vpnState(): VpnState
    }

    fun start(scope: CoroutineScope, repo: SilentRepository, context: Context, listener: Listener) {
        pollJob?.cancel()
        pollJob = scope.launch {
            delay(START_DELAY_MS)
            runCatching { tick(repo, context, listener) }
            while (isActive) {
                delay(POLL_MS)
                if (repo.isLoggedIn() && listener.isPollAllowed()) {
                    runCatching { tick(repo, context, listener) }
                        .onFailure { e ->
                            Log.w(TAG, "tick: ${e.message}")
                            DebugLog.w(TAG, "tick: ${e.message}")
                        }
                }
            }
        }
        wifiSubscriptionJob = scope.launch {
            delay(START_DELAY_MS)
            while (isActive) {
                if (listener.isWifiSubscriptionPollAllowed()) {
                    runCatching { refreshWifiSubscription(repo, listener) }
                        .onFailure { e ->
                            Log.w(TAG, "wifi subscription: ${e.message}")
                            DebugLog.w(TAG, "wifi subscription: ${e.message}")
                        }
                }
                delay(WIFI_SUBSCRIPTION_CHECK_MS)
            }
        }
    }

    suspend fun refreshWifiSubscriptionNow(repo: SilentRepository, listener: Listener) {
        if (!listener.isWifiSubscriptionPollAllowed()) return
        refreshWifiSubscription(repo, listener)
    }

    fun stop() {
        pollJob?.cancel()
        wifiSubscriptionJob?.cancel()
        pollJob = null
        wifiSubscriptionJob = null
    }

    suspend fun tickNow(repo: SilentRepository, context: Context, listener: Listener) {
        if (!repo.isLoggedIn() || !listener.isPollAllowed()) return
        tick(repo, context, listener)
    }

    private fun vpnUpForSync(): Boolean =
        SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            !WdttTunnelManager.isBootstrapMode()

    private suspend fun applyHashItems(
        repo: SilentRepository,
        listener: Listener,
        items: List<HashItemDto>,
        rev: Long? = null,
    ) {
        if (items.isEmpty()) return
        repo.mergeSavedHashesIntoCachedConfig()
        rev?.let { repo.saveSyncHashesRev(it) }
        listener.onHashesUpdated(items, applyToTunnel = vpnUpForSync())
        Log.i(TAG, "hashes updated (${items.size})")
        DebugLog.i(TAG, "hashes updated (${items.size})")
    }

    private suspend fun tick(repo: SilentRepository, context: Context, listener: Listener) {
        tickMutex.withLock {
            val skip = ConfigSyncSkipPolicy.skipReason(
                ConfigSyncSkipPolicy.TickInput(
                    allowsBackgroundSync = repo.allowsBackgroundConfigSync(),
                    vpnBusy = VpnSessionState.isBusy(),
                    initialOverlaySyncActive = VpnSessionState.initialOverlaySyncActive,
                    vpnServiceRunning = SilentVpnService.isRunning,
                    tunnelDataSyncCompleted = VpnSessionState.tunnelDataSyncCompleted,
                    onMobileData = repo.isOnMobileData(),
                    vpnState = listener.vpnState(),
                    nowMs = System.currentTimeMillis(),
                    tunnelDataSyncFinishedAtMs = VpnSessionState.tunnelDataSyncFinishedAtMs,
                ),
            )
            when (skip) {
                ConfigSyncSkipPolicy.SkipReason.MOBILE_WITHOUT_VPN -> {
                    Log.d(TAG, "skip: mobile without VPN tunnel")
                    return
                }
                ConfigSyncSkipPolicy.SkipReason.VPN_BUSY -> {
                    Log.d(TAG, "skip: VPN busy")
                    return
                }
                ConfigSyncSkipPolicy.SkipReason.INITIAL_OVERLAY_SYNC -> {
                    Log.d(TAG, "skip: initial overlay sync in progress")
                    return
                }
                ConfigSyncSkipPolicy.SkipReason.TUNNEL_SYNC_PENDING -> {
                    MobileSyncLog.i("configSync", "skip: initial tunnel sync pending")
                    return
                }
                ConfigSyncSkipPolicy.SkipReason.QUIET_AFTER_TUNNEL_SYNC -> {
                    Log.d(TAG, "skip: quiet period after initial tunnel sync")
                    return
                }
                null -> Unit
            }
            if (
                ConfigSyncSkipPolicy.lteUsesInBandConfigSync(
                    onMobileData = repo.isOnMobileData(),
                    appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                ) && vpnUpForSync()
            ) {
                Log.d(TAG, "skip: LTE in-band GETCONF/DTLS (no HTTP)")
                return
            }
            listener.onWifiSyncTickStart()
            val mobileOverlay = ConfigSyncSkipPolicy.mobileSyncUsesOverlay(
                ConfigSyncSkipPolicy.MobileSyncModeInput(
                    onMobileData = repo.isOnMobileData(),
                    appExcludedFromVpn = SilentRepository.APP_EXCLUDED_FROM_VPN,
                    vpnUpForSync = vpnUpForSync(),
                    tunnelDataSyncCompleted = VpnSessionState.tunnelDataSyncCompleted,
                ),
            )
            if (mobileOverlay) {
                WdttTunnelManager.withApiOverlayBrief(
                    block = { runConfigSyncBody(repo, listener) },
                )
            } else {
                runConfigSyncBody(repo, listener)
            }
        }
    }

    private suspend fun runConfigSyncBody(repo: SilentRepository, listener: Listener) {
        val state = repo.fetchSyncState().getOrNull()
        if (state == null) {
            Log.w(TAG, "sync-state failed")
            return
        }

        val needHashes = state.hashes > repo.getSyncHashesRev()
        val needTheme = state.theme > repo.getSyncThemeRev()
        val needProfile = state.profile > repo.getSyncProfileRev()

        if (!needHashes && !needTheme && !needProfile) {
            Log.d(TAG, "sync-state ok, no changes (h=${state.hashes} t=${state.theme} p=${state.profile})")
            if (!repo.isOnMobileData()) {
                refreshWifiSubscription(repo, listener)
            }
            return
        }

        Log.i(TAG, "sync: hashes=$needHashes theme=$needTheme profile=$needProfile")
        DebugLog.i(TAG, "sync: hashes=$needHashes theme=$needTheme profile=$needProfile")

        if (needHashes) {
            val itemsResult = repo.fetchAndSaveHashItemsForSync()
            val items = itemsResult.getOrNull().orEmpty()
            if (items.isNotEmpty()) {
                applyHashItems(repo, listener, items, state.hashes)
            } else {
                Log.w(TAG, "hashes fetch failed: ${itemsResult.exceptionOrNull()?.message}")
            }
        }
        if (needTheme) {
            repo.fetchAndSaveThemeViaSync().getOrNull()?.let { theme ->
                repo.saveSyncThemeRev(state.theme)
                listener.onTheme(theme)
                Log.i(TAG, "theme updated")
            } ?: Log.w(TAG, "theme fetch failed")
        }
        if (needProfile) {
            repo.fetchAndSaveProfileViaSync().getOrNull()?.let { profile ->
                repo.saveSyncProfileRev(state.profile)
                listener.onProfile(profile)
                Log.i(TAG, "profile updated (devices=${profile.devices.count { it.is_connected }} online)")
            } ?: Log.w(TAG, "profile fetch failed")
        }
    }

    /** Подписка может смениться на сервере без роста profile rev — сверка каждые 2 мин. */
    private suspend fun refreshWifiSubscription(repo: SilentRepository, listener: Listener) {
        if (VpnSessionState.initialOverlaySyncActive) return
        if (repo.isOnMobileData() && !repo.isMainVpnTunnelUp()) return
        val profile = if (repo.isOnMobileData()) {
            repo.fetchProfileLiveViaUser().getOrNull()
        } else {
            repo.fetchProfileLive().getOrNull()
        } ?: run {
            Log.w(TAG, "subscription profile fetch failed")
            return
        }
        listener.onProfile(profile)
        Log.i(TAG, "subscription check active=${profile.subscription.is_active} mobile=${repo.isOnMobileData()}")
        DebugLog.i(TAG, "subscription check active=${profile.subscription.is_active}")
    }
}
