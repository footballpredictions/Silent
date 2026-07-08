package com.silent.vpn.test

import android.util.Log
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager

/** Печатает в logcat текущую сеть — удобно при прогоне на телефоне. */
object DeviceNetworkReporter {
    private const val TAG = "SilentDeviceTest"

    fun logState(context: android.content.Context) {
        val mobile = VpnNetworkHelper.isOnMobileData(context)
        val internet = VpnNetworkHelper.hasAnyUnderlyingInternet(context)
        val vpn = SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value
        Log.i(
            TAG,
            "network: mobileData=$mobile underlyingInternet=$internet silentVpnUp=$vpn",
        )
    }
}
