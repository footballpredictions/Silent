package com.silent.vpn.service

import android.content.Intent
import android.net.VpnService
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.OlcrtcTunnelManager

/**
 * Debug olcrtc: отдельный [VpnService] (SilentVpnService — обычный Service + WG GoBackend).
 */
class OlcrtcVpnService : VpnService() {
    /** Epoch на момент START этой инстанции — stale STOP/onDestroy не трогают новый connect. */
    private var bindEpoch: Int = 0

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        if (action == ACTION_STOP) {
            if (
                OlcrtcTunnelManager.isStarting() ||
                OlcrtcTunnelManager.shouldIgnoreStaleVpnTeardown(bindEpoch)
            ) {
                DebugLog.i(
                    "OlcrtcVpn",
                    "stale STOP ignored bind=$bindEpoch now=${OlcrtcTunnelManager.currentEpoch()} starting=${OlcrtcTunnelManager.isStarting()}",
                )
                return START_STICKY
            }
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
        // Новый START: pending onDestroy прошлого цикла не должен гасить peer.
        suppressDestroyStop = true
        val err = OlcrtcTunnelManager.startFromConfigJson(this, configJson, vpnService = this)
        bindEpoch = OlcrtcTunnelManager.currentEpoch()
        if (err != null) {
            DebugLog.e("OlcrtcVpn", err)
            suppressDestroyStop = false
            OlcrtcTunnelManager.hardReset("vpn_start_fail")
            stopSelf()
            return START_NOT_STICKY
        }
        return START_STICKY
    }

    override fun onRevoke() {
        DebugLog.w("OlcrtcVpn", "revoked")
        if (OlcrtcTunnelManager.shouldIgnoreStaleVpnTeardown(bindEpoch)) {
            DebugLog.i("OlcrtcVpn", "stale revoke ignored — newer session")
            super.onRevoke()
            return
        }
        suppressDestroyStop = false
        OlcrtcTunnelManager.hardReset("vpn_revoked")
        stopSelf()
        super.onRevoke()
    }

    override fun onDestroy() {
        if (
            suppressDestroyStop ||
            OlcrtcTunnelManager.shouldIgnoreStaleVpnTeardown(bindEpoch)
        ) {
            DebugLog.i(
                "OlcrtcVpn",
                "onDestroy skip stop suppress=$suppressDestroyStop bind=$bindEpoch now=${OlcrtcTunnelManager.currentEpoch()}",
            )
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
