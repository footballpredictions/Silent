package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.util.DebugLog

object VpnNetworkHelper {
    private const val TAG = "VpnNetworkHelper"

    /** Активен ли чужой VPN (не Silent). */
    fun isOtherVpnActive(context: Context): Boolean {
        if (SilentVpnService.isRunning) return false
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                DebugLog.i(TAG, "Обнаружен активный VPN другого приложения")
                return true
            }
        }
        return false
    }

    fun hasUnderlyingInternet(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return true
        }
        return false
    }
}
