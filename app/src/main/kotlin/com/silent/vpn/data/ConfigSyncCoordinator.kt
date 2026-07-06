package com.silent.vpn.data

import android.content.Context
import android.util.Log
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
 * Wi‑Fi — public API; mobile + VPN — local proxy → 10.66.66.1 (openConnection, не socketFactory).
 * Фоновый poll — раз в час, чтобы не дёргать WG overlay на LTE.
 */
object ConfigSyncCoordinator {
    private const val TAG = "ConfigSync"
    /** Единый интервал фонового sync (хеши/тема/профиль/подписка). */
    private const val POLL_MS = 60 * 60 * 1000L
    /** Wi‑Fi: rev профиля не растёт при истечении expires_at — отдельная сверка подписки. */
    private const val WIFI_SUBSCRIPTION_CHECK_MS = 2 * 60 * 1000L
    private const val START_DELAY_MS = 5_000L
    /** Не трогаем ConfigSync сразу после initial sync — rev уже записан в VpnDataSyncService. */
    private const val POST_TUNNEL_SYNC_QUIET_MS = 90_000L

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
            if (!repo.allowsBackgroundConfigSync()) {
                Log.d(TAG, "skip: mobile without VPN tunnel")
                return
            }
            listener.onWifiSyncTickStart()

            if (VpnSessionState.isBusy()) {
                Log.d(TAG, "skip: VPN busy")
                return
            }
            if (VpnSessionState.initialOverlaySyncActive) {
                Log.d(TAG, "skip: initial overlay sync in progress")
                return
            }
            if (SilentVpnService.isRunning &&
                !VpnSessionState.tunnelDataSyncCompleted &&
                (listener.vpnState() == VpnState.CONNECTING || repo.isOnMobileData())
            ) {
                MobileSyncLog.i("configSync", "skip: initial tunnel sync pending")
                return
            }
            if (repo.isOnMobileData() &&
                VpnSessionState.tunnelDataSyncCompleted &&
                System.currentTimeMillis() - VpnSessionState.tunnelDataSyncFinishedAtMs < POST_TUNNEL_SYNC_QUIET_MS
            ) {
                Log.d(TAG, "skip: quiet period after initial tunnel sync")
                return
            }

            if (repo.isOnMobileData() && SilentRepository.APP_EXCLUDED_FROM_VPN && vpnUpForSync()) {
                if (VpnSessionState.tunnelDataSyncCompleted) {
                    runConfigSyncBody(repo, listener)
                } else {
                    WdttTunnelManager.withApiOverlayBrief(
                        block = { runConfigSyncBody(repo, listener) },
                    )
                }
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

    /** Wi‑Fi public API: подписка может истечь/появиться без роста profile rev. */
    private suspend fun refreshWifiSubscription(repo: SilentRepository, listener: Listener) {
        if (repo.isOnMobileData()) return
        if (VpnSessionState.initialOverlaySyncActive) return
        repo.fetchAndSaveProfileViaSync().getOrNull()?.let { profile ->
            listener.onProfile(profile)
            Log.i(TAG, "wifi subscription check active=${profile.subscription.is_active}")
            DebugLog.i(TAG, "wifi subscription check active=${profile.subscription.is_active}")
        } ?: Log.w(TAG, "wifi subscription profile fetch failed")
    }
}
