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

    /** После force-kill / залипшей плитки — WG или libclient могли остаться в системе. */
    fun needsStaleCleanup(context: Context): Boolean {
        if (SilentVpnService.isRunning && WdttTunnelManager.running.value && WdttTunnelManager.tunnelReady.value) {
            return false
        }
        return VpnServiceTracker.isSessionMarkedActive(context) ||
            WdttTunnelManager.running.value ||
            WdttTunnelManager.tunnelReady.value ||
            VpnNetworkHelper.findOurVpnNetwork(context) != null
    }

    /**
     * Перед CONNECT: сброс orphan WG + полная очистка только при stale.
     * Вызывать один раз из SilentVpnService (плитка не дублирует).
     */
    fun prepareForConnect(context: Context) {
        synchronized(lock) {
            val appCtx = context.applicationContext
            runBlocking {
                runCatching { WdttTunnelManager.ensureApiOverlayOff() }
                runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                    .onFailure { e -> DebugLog.w(TAG, "forceStopSilentTunnel: ${e.message}") }
            }
            if (!needsStaleCleanup(context)) {
                SessionTrace.mark("VpnConnectHelper.prepareForConnect", "WG reset, libclient clean")
                return
            }
            ensureCleanSlateLocked(appCtx, force = true, stale = true)
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
        WdttTunnelManager.clearStaleSession()
        SilentVpnService.resetStaleSession()
        VpnBackendSync.stop()
        VpnSessionState.resetBackendSync()
        VpnServiceTracker.markSessionActive(appCtx, false)
        VpnTileHelper.requestUpdate(appCtx)
        lastCleanSlateAtMs = System.currentTimeMillis()
    }
}
