package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardHelper
import kotlinx.coroutines.runBlocking

/** Чистый старт VPN — после kill процесса с включённым VPN / залипшей плитки. */
object VpnConnectHelper {
    private const val TAG = "VpnConnectHelper"

    /** Между CONNECT подряд (плитка → сервис) — не чистить дважды. */
    private const val CLEAN_SLATE_DEDUPE_MS = 3_000L

    private val lock = Any()

    @Volatile
    private var lastCleanSlateAtMs = 0L

    /** После reconcile / ensureCleanSlate — не гонять stopAndAwait повторно при CONNECT. */
    fun noteCleanSlate() {
        synchronized(lock) {
            lastCleanSlateAtMs = System.currentTimeMillis()
        }
    }

    /** После force-kill / залипшей плитки — WG или libclient могли остаться в системе. */
    fun needsStaleCleanup(context: Context): Boolean {
        if (SilentVpnService.isRunning && WdttTunnelManager.isTransportReadyStrict()) {
            return false
        }
        return VpnServiceTracker.isSessionMarkedActive(context) ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.tunnelReady.value ||
            VpnNetworkHelper.findOurVpnNetwork(context) != null
    }

    /**
     * Сброс только runtime VPN (флаги, in-memory) — без токенов, кеша конфига и хешей.
     * После OTA или залипшей плитки.
     */
    fun resetRuntimeFlags(context: Context) {
        synchronized(lock) {
            resetRuntimeFlagsLocked(context.applicationContext)
        }
    }

    /**
     * QS-плитка OFF→ON: гарантированно остановить libclient/WG перед новым CONNECT.
     * Не трогает логин, cached_vpn_config, saved_hash_items.
     */
    fun prepareForTileReconnect(context: Context) {
        synchronized(lock) {
            val appCtx = context.applicationContext
            SessionTrace.mark("VpnConnectHelper.prepareForTileReconnect")
            val now = System.currentTimeMillis()
            if (now - lastCleanSlateAtMs < CLEAN_SLATE_DEDUPE_MS) {
                SessionTrace.mark("VpnConnectHelper.prepareForTileReconnect", "skip recent clean")
                return
            }
            val orphanWg = VpnNetworkHelper.findOurVpnNetwork(appCtx) != null
            val stale = needsStaleCleanup(appCtx)
            if (!orphanWg && !stale) {
                SessionTrace.mark("VpnConnectHelper.prepareForTileReconnect", "skip already clean")
                return
            }
            runBlocking {
                if (orphanWg || WdttTunnelManager.running.value || stale) {
                    runCatching { WdttTunnelManager.stopAndAwait() }
                        .onFailure { e -> DebugLog.w(TAG, "tile reconnect stopAndAwait: ${e.message}") }
                }
                if (orphanWg) {
                    runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                        .onFailure { e -> DebugLog.w(TAG, "tile reconnect forceStop: ${e.message}") }
                }
            }
            resetRuntimeFlagsLocked(appCtx)
            lastCleanSlateAtMs = System.currentTimeMillis()
            VpnTileHelper.requestUpdate(appCtx)
        }
    }

    /**
     * Перед CONNECT из приложения: полная очистка только при stale/orphan WG.
     */
    fun prepareForConnect(context: Context) {
        synchronized(lock) {
            val appCtx = context.applicationContext
            val orphanWg = VpnNetworkHelper.findOurVpnNetwork(appCtx) != null
            val stale = needsStaleCleanup(context)
            WdttTunnelManager.ensureApiOverlayOff()
            VpnBackendSync.stop()
            VpnSessionState.resetBackendSync()
            if (!orphanWg && !stale) {
                SessionTrace.mark("VpnConnectHelper.prepareForConnect", "clean reconnect — skip WG reset")
                return
            }
            SessionTrace.mark("VpnConnectHelper.prepareForConnect", "orphanWg=$orphanWg stale=$stale")
            runBlocking {
                if (orphanWg || WdttTunnelManager.running.value) {
                    runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                        .onFailure { e -> DebugLog.w(TAG, "forceStopSilentTunnel: ${e.message}") }
                }
            }
            if (stale) {
                ensureCleanSlateLocked(appCtx, force = true, stale = true)
            }
        }
    }

    /**
     * Полная очистка libclient + WG (после kill / таймаута).
     */
    fun ensureCleanSlate(context: Context, force: Boolean = false) {
        synchronized(lock) {
            val stale = needsStaleCleanup(context)
            val now = System.currentTimeMillis()
            if (!stale) {
                if (now - lastCleanSlateAtMs < CLEAN_SLATE_DEDUPE_MS) {
                    SessionTrace.mark("VpnConnectHelper.ensureCleanSlate", "skip (recent, clean)")
                    return
                }
                SessionTrace.mark("VpnConnectHelper.ensureCleanSlate", "skip (already clean)")
                return
            }
            if (!force && now - lastCleanSlateAtMs < CLEAN_SLATE_DEDUPE_MS) {
                SessionTrace.mark("VpnConnectHelper.ensureCleanSlate", "skip (recent stale dedupe)")
                return
            }
            ensureCleanSlateLocked(context.applicationContext, force, stale)
        }
    }

    private fun ensureCleanSlateLocked(appCtx: Context, force: Boolean, stale: Boolean) {
        SessionTrace.mark("VpnConnectHelper.ensureCleanSlate", "force=$force stale=$stale")
        runBlocking {
            runCatching { WdttTunnelManager.stopAndAwait() }
                .onFailure { e -> DebugLog.w(TAG, "stopAndAwait: ${e.message}") }
            runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                .onFailure { e -> DebugLog.w(TAG, "forceStopSilentTunnel: ${e.message}") }
        }
        resetRuntimeFlagsLocked(appCtx)
        lastCleanSlateAtMs = System.currentTimeMillis()
        VpnTileHelper.requestUpdate(appCtx)
    }

    private fun resetRuntimeFlagsLocked(appCtx: Context) {
        WdttTunnelManager.clearStaleSession()
        SilentVpnService.resetStaleSession()
        VpnBackendSync.stop()
        VpnSessionState.resetBackendSync()
        VpnServiceTracker.markSessionActive(appCtx, false)
        WdttTunnelManager.ensureApiOverlayOff()
    }
}
