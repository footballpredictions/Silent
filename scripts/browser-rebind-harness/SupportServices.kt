package com.silent.vpn.service

class BrowserScopedVpnService : android.net.VpnService() {
    companion object { var instance: BrowserScopedVpnService? = null }
}

class SilentVpnService : android.app.Service() {
    override fun onBind(intent: android.content.Intent?): android.os.IBinder? = null
    companion object { const val ACTION_EXTERNAL_REVOKED = "revoke" }
}
