package com.silent.vpn

import android.app.Application
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import com.silent.vpn.data.AppStateMigration
import com.silent.vpn.di.AppEntryPoint
import com.silent.vpn.service.VpnServiceTracker
import com.silent.vpn.service.VpnTileHelper
import com.silent.vpn.util.DevicePlatform
import com.silent.vpn.util.SessionTrace
import dagger.hilt.android.EntryPointAccessors
import com.wireguard.android.backend.GoBackend
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class SilentApp : Application() {
    override fun onCreate() {
        super.onCreate()
        SessionTrace.mark("SilentApp.onCreate", BuildConfig.VERSION_NAME)
        AppStateMigration.runIfNeeded(this)
        Thread {
            runCatching {
                EntryPointAccessors.fromApplication(this, AppEntryPoint::class.java)
                    .silentRepository()
                    .getCachedTheme()
            }
        }.start()
        // Только reconcile — полная очистка один раз в SilentVpnService.CONNECT (не блокировать плитку).
        VpnServiceTracker.reconcileStaleSession(this)
        Thread {
            runCatching { getBackend(this) }
        }.start()
        VpnTileHelper.requestUpdate(this)
        if (DevicePlatform.isTv(this)) {
            Handler(Looper.getMainLooper()).post {
                runCatching {
                    WebView(applicationContext).destroy()
                }
            }
        }
    }

    @Volatile
    private var backendInstance: GoBackend? = null

    fun getBackend(context: Context): GoBackend {
        return backendInstance ?: synchronized(this) {
            backendInstance ?: GoBackend(context.applicationContext).also { backendInstance = it }
        }
    }
}
