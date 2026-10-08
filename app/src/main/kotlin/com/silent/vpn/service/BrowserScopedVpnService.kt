package com.silent.vpn.service

import android.content.Intent
import android.net.VpnService
import com.silent.vpn.vpn.BrowserScopedTunnel

/** One TUN for all participating apps; browser address rules run per connection. */
class BrowserScopedVpnService : VpnService() {
    companion object {
        @Volatile var instance: BrowserScopedVpnService? = null
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this
    }

    override fun onRevoke() {
        BrowserScopedTunnel.stop()
        startService(Intent(this, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_EXTERNAL_REVOKED
        })
        super.onRevoke()
    }

    override fun onDestroy() {
        instance = null
        BrowserScopedTunnel.stop()
        super.onDestroy()
    }
}
