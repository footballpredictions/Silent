package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.ConnectRequest
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.EntryPointAccessors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/** Online heartbeat и tunnel API — из сервиса, чтобы плитка QS тоже отмечала устройство онлайн. */
object VpnBackendSync {
    private const val TAG = "VpnBackendSync"
    private const val MAINTENANCE_MS = 5 * 60_000L

    private var initialJob: Job? = null
    private var maintenanceJob: Job? = null

    private fun repo(context: Context): SilentRepository =
        EntryPointAccessors.fromApplication(context.applicationContext, AppEntryPoint::class.java)
            .silentRepository()

    fun ensureRunning(scope: CoroutineScope, context: Context) {
        SessionTrace.mark("VpnBackendSync.ensureRunning", "running=${SilentVpnService.isRunning}")
        if (!SilentVpnService.isRunning || !repo(context).isLoggedIn()) return
        if (VpnSessionState.backendSyncCompleted && maintenanceJob?.isActive == true) return
        scheduleInitialSync(scope, context.applicationContext)
    }

    fun stop() {
        SessionTrace.mark("VpnBackendSync.stop")
        initialJob?.cancel()
        initialJob = null
        maintenanceJob?.cancel()
        maintenanceJob = null
        VpnSessionState.resetBackendSync()
    }

    /** Снять устройство с «онлайн» на backend (плитка / сервис без MainViewModel). */
    suspend fun notifyDisconnect(context: Context) {
        val r = repo(context)
        if (!r.isLoggedIn()) return
        runCatching {
            if (r.needsTunnelApiOverlay() && WdttTunnelManager.tunnelReady.value) {
                r.withTunnelApiWhenExcluded {
                    r.getApi().disconnect(DisconnectRequest(r.getDeviceFingerprint()))
                }
            } else {
                r.getApi().disconnect(DisconnectRequest(r.getDeviceFingerprint()))
            }
        }.onFailure { e ->
            DebugLog.w(TAG, "disconnect API skipped: ${e.message}")
        }
    }

    private fun scheduleInitialSync(scope: CoroutineScope, context: Context) {
        if (initialJob?.isActive == true) {
            SessionTrace.mark("VpnBackendSync.scheduleInitialSync", "already running")
            return
        }
        SessionTrace.enter("VpnBackendSync.scheduleInitialSync")
        initialJob = scope.launch {
            if (!SilentVpnService.isRunning) {
                SessionTrace.exit("VpnBackendSync.scheduleInitialSync", "service stopped")
                return@launch
            }
            val r = repo(context)
            if (!r.isLoggedIn()) {
                SessionTrace.exit("VpnBackendSync.scheduleInitialSync", "not logged in")
                return@launch
            }

            SessionTrace.wait("VpnBackendSync", "awaitWgConfigSettled")
            WdttTunnelManager.awaitWgConfigSettled()
            if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) {
                SessionTrace.exit("VpnBackendSync.scheduleInitialSync", "tunnel not ready")
                return@launch
            }

            val deadline = System.currentTimeMillis() + 180_000L
            while (
                System.currentTimeMillis() < deadline &&
                WdttTunnelManager.isWorkerRampUpActive() &&
                SilentVpnService.isRunning
            ) {
                SessionTrace.wait("VpnBackendSync", "ramp-up workers=${WdttTunnelManager.activeWorkers.value}")
                delay(1_000)
            }
            delay(2_000)
            if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) {
                SessionTrace.exit("VpnBackendSync.scheduleInitialSync", "tunnel lost")
                return@launch
            }
            if (VpnSessionState.backendSyncCompleted) {
                SessionTrace.mark("VpnBackendSync.scheduleInitialSync", "maintenance only")
                startMaintenance(scope, context)
                SessionTrace.exit("VpnBackendSync.scheduleInitialSync")
                return@launch
            }

            SessionTrace.enter("VpnBackendSync.runInitialSync")
            runInitialSync(context)
            SessionTrace.exit("VpnBackendSync.runInitialSync")
            VpnSessionState.backendSyncCompleted = true
            startMaintenance(scope, context)
            SessionTrace.exit("VpnBackendSync.scheduleInitialSync", "done")
        }
    }

    private suspend fun runInitialSync(context: Context) {
        val r = repo(context)
        val tunnel = r.tunnelApiBaseUrl()
        DebugLog.i(TAG, "initial online sync via $tunnel")
        if (!r.needsTunnelApiOverlay()) {
            runCatching {
                val res = r.getApi().connect(ConnectRequest(r.getDeviceFingerprint(), "android"))
                if (res.isSuccessful) DebugLog.i(TAG, "online heartbeat OK")
            }
            return
        }
        runCatching {
            r.withTunnelApiForInitialSync {
                runCatching {
                    val res = r.getApi().connect(ConnectRequest(r.getDeviceFingerprint(), "android"))
                    if (res.isSuccessful) {
                        DebugLog.i(TAG, "online heartbeat OK (tunnel API)")
                    } else {
                        DebugLog.w(TAG, "online sync HTTP ${res.code()}")
                    }
                }
            }
        }.onFailure { e ->
            DebugLog.w(TAG, "initial sync skipped: ${e.message}")
        }
    }

    private fun startMaintenance(scope: CoroutineScope, context: Context) {
        if (maintenanceJob?.isActive == true) return
        SessionTrace.mark("VpnBackendSync.startMaintenance")
        maintenanceJob = scope.launch {
            while (isActive && SilentVpnService.isRunning && VpnSessionState.isActive()) {
                delay(MAINTENANCE_MS)
                if (!SilentVpnService.isRunning || !repo(context).isLoggedIn()) break
                if (WdttTunnelManager.isWorkerRampUpActive()) continue
                runCatching { runMaintenancePulse(context.applicationContext) }
            }
            SessionTrace.mark("VpnBackendSync.maintenance", "loop ended")
        }
    }

    private suspend fun runMaintenancePulse(context: Context) {
        val r = repo(context)
        if (!r.isLoggedIn()) return
        runCatching {
            r.withTunnelApiWhenExcluded {
                runCatching {
                    val res = r.getApi().connect(ConnectRequest(r.getDeviceFingerprint(), "android"))
                    if (res.isSuccessful) DebugLog.i(TAG, "online heartbeat OK (maintenance)")
                }
            }
        }.onFailure { e ->
            DebugLog.w(TAG, "maintenance sync skipped: ${e.message}")
        }
    }
}

