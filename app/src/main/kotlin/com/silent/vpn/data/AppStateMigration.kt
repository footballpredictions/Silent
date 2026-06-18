package com.silent.vpn.data

import android.content.Context
import com.silent.vpn.BuildConfig
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.service.VpnServiceTracker
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.WdttTunnelManager

/**
 * Одноразовая миграция после OTA — без чистой переустановки.
 * Сбрасывает залипший кеш VPN/профиля, который ломает POST /connect.
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

        if (!SilentVpnService.isRunning && !WdttTunnelManager.running.value) {
            VpnServiceTracker.markSessionActive(appCtx, false)
        }

        val loggedIn = !prefs.getString(SilentRepository.PREF_ACCESS_TOKEN, null).isNullOrBlank()
        if (loggedIn) {
            val stable = prefs.getString(SilentRepository.PREF_STABLE_FP, null)?.trim().orEmpty()
            val fp = prefs.getString(SilentRepository.PREF_DEVICE_FP, null)?.trim().orEmpty()
            when {
                fp.isBlank() && stable.isNotBlank() ->
                    prefs.edit().putString(SilentRepository.PREF_DEVICE_FP, stable).apply()
            }
            // VPN-конфиг и сохранённые хеши не сбрасываем — иначе на мобильном connect невозможен.
        }

        prefs.edit().putInt(PREF_MIGRATED_VERSION, BuildConfig.VERSION_CODE).apply()
    }
}
