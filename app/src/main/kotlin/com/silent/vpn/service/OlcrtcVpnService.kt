package com.silent.vpn.service

import android.content.Intent
import android.net.VpnService
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.OlcrtcTunnelManager

/**
 * Debug olcrtc: отдельный [VpnService] (SilentVpnService — обычный Service + WG GoBackend).
 */
class OlcrtcVpnService : VpnService() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        if (action == ACTION_STOP) {
            // Всегда полный native reset — иначе TM→WB без kill app = «вкл, не пашет».
            suppressDestroyStop = false
            OlcrtcTunnelManager.hardReset("vpn_ACTION_STOP")
            stopSelf()
            return START_NOT_STICKY
        }
        val configJson = intent?.getStringExtra(EXTRA_CONFIG)
        if (configJson.isNullOrBlank()) {
            DebugLog.e("OlcrtcVpn", "no config")
            stopSelf()
            return START_NOT_STICKY
        }
        // Новый START после STOP — onDestroy предыдущего цикла не должен гасить peer.
        suppressDestroyStop = false
        val err = OlcrtcTunnelManager.startFromConfigJson(this, configJson, vpnService = this)
        if (err != null) {
            DebugLog.e("OlcrtcVpn", err)
            OlcrtcTunnelManager.hardReset("vpn_start_fail")
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onRevoke() {
        DebugLog.w("OlcrtcVpn", "revoked")
        suppressDestroyStop = false
        OlcrtcTunnelManager.hardReset("vpn_revoked")
        stopSelf()
        super.onRevoke()
    }

    override fun onDestroy() {
        if (suppressDestroyStop) {
            DebugLog.i("OlcrtcVpn", "onDestroy skip stop (reconnect in flight)")
        } else {
            OlcrtcTunnelManager.hardReset("vpn_onDestroy")
        }
        suppressDestroyStop = false
        super.onDestroy()
    }

    companion object {
        const val ACTION_START = "com.silent.vpn.OLCRTC_VPN_START"
        const val ACTION_STOP = "com.silent.vpn.OLCRTC_VPN_STOP"
        const val EXTRA_CONFIG = "olcrtc_config_json"

        /**
         * SilentVpnService.recoverOlcrtc: STOP→START — не дать onDestroy убить новый процесс.
         */
        @Volatile
        var suppressDestroyStop: Boolean = false
    }
}
