package com.silent.vpn.data

import android.content.Context
import android.util.Log
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
 * Канал обновлений: sync-state → profile, hashes, theme.
 * Wi‑Fi — public API; mobile — только при поднятом VPN (tunnel proxy, без WG overlay).
 */
object ConfigSyncCoordinator {
    private const val TAG = "ConfigSync"
    private const val POLL_MS = 45_000L
    private const val START_DELAY_MS = 5_000L

    private val tickMutex = Mutex()
    private var pollJob: Job? = null

    interface Listener {
        fun onTheme(theme: ThemeData)
        fun onProfile(profile: UserProfile)
        fun onHashesUpdated(items: List<HashItemDto>, applyToTunnel: Boolean)
        fun onWifiSyncTickStart()
        fun isPollAllowed(): Boolean
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
    }

    fun stop() {
        pollJob?.cancel()
        pollJob = null
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
            if (SilentVpnService.isRunning &&
                !VpnSessionState.tunnelDataSyncCompleted &&
                listener.vpnState() == VpnState.CONNECTING
            ) {
                Log.d(TAG, "skip: initial connect sync")
                return
            }

            val stateResult = repo.fetchSyncState()
            val state = stateResult.getOrNull()
            if (state == null) {
                Log.w(TAG, "sync-state failed: ${stateResult.exceptionOrNull()?.message}")
                return
            }

            val needHashes = state.hashes > repo.getSyncHashesRev()
            val needTheme = state.theme > repo.getSyncThemeRev()
            val needProfile = state.profile > repo.getSyncProfileRev()

            if (!needHashes && !needTheme && !needProfile) {
                Log.d(TAG, "sync-state ok, no changes (h=${state.hashes} t=${state.theme} p=${state.profile})")
                if (!vpnUpForSync()) return
            } else {
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

            // Пока main VPN активен — всегда сверяем подписку с сервером (rev мог не измениться).
            if (vpnUpForSync()) {
                repo.fetchProfileLiveViaUser().getOrNull()?.let { profile ->
                    listener.onProfile(profile)
                    Log.i(TAG, "subscription check profile active=${profile.subscription.is_active}")
                } ?: Log.w(TAG, "subscription profile fetch failed")
            }
        }
    }
}
