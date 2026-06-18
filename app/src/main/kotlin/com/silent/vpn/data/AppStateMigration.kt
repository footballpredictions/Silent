package com.silent.vpn.data

import android.content.Context
import com.silent.vpn.BuildConfig
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.service.VpnConnectHelper
import com.silent.vpn.service.VpnServiceTracker
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.WireGuardHelper
import kotlinx.coroutines.runBlocking

/**
 * Одноразовая миграция после OTA — без чистой переустановки.
 * Сбрасывает залипший runtime VPN (не токены / кеш конфига / хеши).
 */
object AppStateMigration {
    private const val TAG = "AppStateMigration"
    private const val PREF_MIGRATED_VERSION = "app_migrated_version_code"

    fun runIfNeeded(context: Context) {
        val appCtx = context.applicationContext
        val prefs = SilentPrefs.open(appCtx)
        val last = prefs.getInt(PREF_MIGRATED_VERSION, 0)
        if (last >= BuildConfig.VERSION_CODE) return

        DebugLog.i(TAG, "migrate $last → ${BuildConfig.VERSION_CODE}")

        val transportLive = SilentVpnService.isRunning || WdttTunnelManager.running.value
        if (!transportLive) {
            VpnConnectHelper.resetRuntimeFlags(appCtx)
            val orphanWg = VpnNetworkHelper.findOurVpnNetwork(appCtx) != null
            if (orphanWg) {
                runBlocking {
                    runCatching { WireGuardHelper(appCtx).forceStopSilentTunnel() }
                        .onFailure { e -> DebugLog.w(TAG, "OTA orphan WG cleanup: ${e.message}") }
                }
            }
        } else {
            VpnServiceTracker.markSessionActive(appCtx, true)
        }

        val loggedIn = !prefs.getString(SilentRepository.PREF_ACCESS_TOKEN, null).isNullOrBlank()
        if (loggedIn) {
            val stable = prefs.getString(SilentRepository.PREF_STABLE_FP, null)?.trim().orEmpty()
            val fp = prefs.getString(SilentRepository.PREF_DEVICE_FP, null)?.trim().orEmpty()
            when {
                fp.isBlank() && stable.isNotBlank() ->
                    prefs.edit().putString(SilentRepository.PREF_DEVICE_FP, stable).apply()
            }
        }

        prefs.edit().putInt(PREF_MIGRATED_VERSION, BuildConfig.VERSION_CODE).apply()
    }
}
