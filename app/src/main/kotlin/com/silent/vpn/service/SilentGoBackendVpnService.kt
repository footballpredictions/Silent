package com.silent.vpn.service

import android.content.Intent
import com.silent.vpn.util.DebugLog
import com.wireguard.android.backend.GoBackend

/** Перехват onRevoke — только когда другой VPN реально подключился (не при простом открытии приложения). */
class SilentGoBackendVpnService : GoBackend.VpnService() {

    override fun onRevoke() {
        DebugLog.w("GoBackendVpn", "VPN revoked by system (another VPN connected)")
        super.onRevoke()
        if (SilentVpnService.isRunning) {
            startService(
                Intent(this, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_EXTERNAL_REVOKED
                },
            )
        }
    }
}
