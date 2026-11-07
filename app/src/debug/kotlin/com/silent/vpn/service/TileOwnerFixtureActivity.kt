package com.silent.vpn.service

import android.app.Activity
import android.os.Bundle

/** Seeds the real QS owner signal in an ordinary app process, without a VPN/account.
 * Killing instrumentation would force-stop the package and distort SystemUI binding.
 */
class TileOwnerFixtureActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            SilentVpnService::class.java.getDeclaredField("isRunning").apply {
                isAccessible = true
                setBoolean(null, intent.getBooleanExtra("enabled", true))
            }
            VpnTileHelper.requestUpdate(applicationContext)
        } finally {
            finish()
        }
    }
}
