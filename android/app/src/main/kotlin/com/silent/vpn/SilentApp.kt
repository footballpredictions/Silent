package com.silent.vpn

import android.app.Application
import android.content.Context
import com.silent.vpn.data.AppStateMigration
import com.silent.vpn.service.VpnServiceTracker
import com.silent.vpn.service.VpnTileHelper
import com.silent.vpn.util.SessionTrace
import com.wireguard.android.backend.GoBackend
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class SilentApp : Application() {
    override fun onCreate() {
        super.onCreate()
        SessionTrace.mark("SilentApp.onCreate", BuildConfig.VERSION_NAME)
        AppStateMigration.runIfNeeded(this)
        // Только reconcile — полная очистка один раз в SilentVpnService.CONNECT (не блокировать плитку).
        VpnServiceTracker.reconcileStaleSession(this)
        Thread {
            runCatching { getBackend(this) }
        }.start()
        VpnTileHelper.requestUpdate(this)
    }

    @Volatile
    private var backendInstance: GoBackend? = null

    fun getBackend(context: Context): GoBackend {
        return backendInstance ?: synchronized(this) {
            backendInstance ?: GoBackend(context.applicationContext).also { backendInstance = it }
        }
    }
}
