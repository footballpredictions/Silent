package com.silent.vpn.service

import android.content.Context
import com.silent.vpn.data.ConnectRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.util.DebugLog
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
        if (!SilentVpnService.isRunning || !repo(context).isLoggedIn()) return
        if (VpnSessionState.backendSyncCompleted && maintenanceJob?.isActive == true) return
        scheduleInitialSync(scope, context.applicationContext)
    }

    fun stop() {
        initialJob?.cancel()
        initialJob = null
        maintenanceJob?.cancel()
        maintenanceJob = null
        VpnSessionState.resetBackendSync()
    }

    private fun scheduleInitialSync(scope: CoroutineScope, context: Context) {
        if (initialJob?.isActive == true) return
        initialJob = scope.launch {
            if (!SilentVpnService.isRunning) return@launch
            val r = repo(context)
            if (!r.isLoggedIn()) return@launch

            WdttTunnelManager.awaitWgConfigSettled()
            if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) return@launch

            val deadline = System.currentTimeMillis() + 180_000L
            while (
                System.currentTimeMillis() < deadline &&
                WdttTunnelManager.isWorkerRampUpActive() &&
                SilentVpnService.isRunning
            ) {
                delay(1_000)
            }
            delay(2_000)
            if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) return@launch
            if (VpnSessionState.backendSyncCompleted) {
                startMaintenance(scope, context)
                return@launch
            }

            runInitialSync(context)
            VpnSessionState.backendSyncCompleted = true
            startMaintenance(scope, context)
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
        r.withTunnelApiWhenExcluded {
            runCatching {
                val res = r.getApi().connect(ConnectRequest(r.getDeviceFingerprint(), "android"))
                if (res.isSuccessful) {
                    DebugLog.i(TAG, "online heartbeat OK (tunnel API)")
                } else {
                    DebugLog.w(TAG, "online sync HTTP ${res.code()}")
                }
            }
        }
    }

    private fun startMaintenance(scope: CoroutineScope, context: Context) {
        if (maintenanceJob?.isActive == true) return
        maintenanceJob = scope.launch {
            while (isActive && SilentVpnService.isRunning && VpnSessionState.isActive()) {
                delay(MAINTENANCE_MS)
                if (!SilentVpnService.isRunning || !repo(context).isLoggedIn()) break
                if (WdttTunnelManager.isWorkerRampUpActive()) continue
                runCatching { runMaintenancePulse(context.applicationContext) }
            }
        }
    }

    private suspend fun runMaintenancePulse(context: Context) {
        val r = repo(context)
        if (!r.isLoggedIn()) return
        r.withTunnelApiWhenExcluded {
            runCatching {
                val res = r.getApi().connect(ConnectRequest(r.getDeviceFingerprint(), "android"))
                if (res.isSuccessful) DebugLog.i(TAG, "online heartbeat OK (maintenance)")
            }
        }
    }
}
