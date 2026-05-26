package com.silent.vpn

import android.app.Application
import android.content.Context
import com.wireguard.android.backend.GoBackend
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class SilentApp : Application() {
    @Volatile
    private var backendInstance: GoBackend? = null

    fun getBackend(context: Context): GoBackend {
        return backendInstance ?: synchronized(this) {
            backendInstance ?: GoBackend(context.applicationContext).also { backendInstance = it }
        }
    }
}
