package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Build
import com.silent.vpn.policy.OlcrtcRecoveryPolicy
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.delay

object VpnNetworkHelper {
    private const val TAG = "VpnNetworkHelper"

    /** getConnectionOwnerUid(Network) — API 31+, через reflection (stub на части SDK). */
    fun vpnOwnerUid(cm: ConnectivityManager, network: Network): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return -1
        return runCatching {
            ConnectivityManager::class.java
                .getMethod("getConnectionOwnerUid", Network::class.java)
                .invoke(cm, network) as Int
        }.getOrDefault(-1)
    }

    /** Активен ли чужой VPN (не Silent). Только реально подключённый туннель другого uid. */
    fun isOtherVpnActive(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val ourUid = context.applicationInfo.uid
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val owner = vpnOwnerUid(cm, network)
                if (owner == ourUid) continue
                if (owner > 0) {
                    DebugLog.i(TAG, "Обнаружен активный VPN другого приложения (uid=$owner)")
                    return true
                }
            } else if (SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) {
                continue
            } else {
                DebugLog.i(TAG, "Обнаружен активный VPN (legacy check)")
                return true
            }
        }
        return false
    }

    /** WireGuard-сеть Silent (в т.ч. после kill процесса — без проверки isRunning). */
    fun findOurVpnNetwork(context: Context): Network? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val ourUid = context.applicationInfo.uid
        var fallback: Network? = null
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val owner = vpnOwnerUid(cm, network)
                if (owner > 0 && owner != ourUid) continue
            }
            if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
                return network
            }
            if (fallback == null) fallback = network
        }
        return fallback
    }

    /** WireGuard-сеть Silent — для HTTP к 10.66.66.1 когда app исключён из туннеля. */
    fun getSilentVpnNetwork(context: Context): Network? {
        if (!SilentVpnService.isRunning && !WdttTunnelManager.tunnelReady.value) return null
        findOurVpnNetwork(context)?.let { return it }
        if (!SilentVpnService.isRunning) return null
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) continue
            if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
                DebugLog.i(TAG, "VPN network fallback (any VPN w/ internet)")
                return network
            }
        }
        return null
    }

    fun hasUnderlyingInternet(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) continue
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M &&
                !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
            ) {
                continue
            }
            return true
        }
        return false
    }

    /** Есть ли NOT_VPN сеть с INTERNET (без требования VALIDATED — для детекта полного обрыва). */
    fun hasAnyUnderlyingInternet(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            if (caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) return true
        }
        return false
    }

    /** Cellular без активного Wi‑Fi/Ethernet (Wi‑Fi радио «вкл» без сети не считается). */
    fun isOnMobileData(context: Context): Boolean {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        var cellInternet = false
        var wifiInternet = false
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) continue
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) {
                DebugLog.i(TAG, "isOnMobileData=false (ethernet)")
                return false
            }
            if (hasUsableWifi(caps)) wifiInternet = true
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) cellInternet = true
        }
        val onMobile = cellInternet && !wifiInternet
        DebugLog.i(TAG, "isOnMobileData=$onMobile cell=$cellInternet wifi=$wifiInternet")
        return onMobile
    }

    /**
     * Тип underlying (NOT_VPN) для Wi‑Fi↔LTE: eth > wifi > cell.
     * Не смотрит default/VPN — иначе при живом туннеле fingerprint всегда «unknown».
     */
    fun underlyingTransportFingerprint(context: Context): String {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        var hasEth = false
        var hasWifi = false
        var hasCell = false
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)) continue
            if (!caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) continue
            when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> hasEth = true
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> hasWifi = true
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> hasCell = true
            }
        }
        return when {
            hasEth -> "eth"
            hasWifi -> "wifi"
            hasCell -> "cell"
            else -> ""
        }
    }

    /**
     * Ждём underlying сеть. [preferTransport]: "wifi"|"cell"|null.
     * После [preferHoldMs] принимаем любой VALIDATED/any — иначе LTE после самолёта залипает
     * на ожидании wifi, которого уже нет.
     */
    suspend fun awaitUnderlyingReady(
        context: Context,
        timeoutMs: Long = 20_000L,
        preferTransport: String? = null,
        preferHoldMs: Long = 4_000L,
    ): Boolean {
        val started = System.currentTimeMillis()
        val deadline = started + timeoutMs
        val want = OlcrtcRecoveryPolicy.normalizePreferTransport(preferTransport)
        while (System.currentTimeMillis() < deadline) {
            val elapsed = System.currentTimeMillis() - started
            val fp = underlyingTransportFingerprint(context)
            val validated = hasUnderlyingInternet(context)
            val any = hasAnyUnderlyingInternet(context)
            if (
                OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                    OlcrtcRecoveryPolicy.UnderlyingReadySample(
                        elapsedMs = elapsed,
                        fingerprint = fp,
                        validated = validated,
                        anyInternet = any,
                        preferTransport = preferTransport,
                        preferHoldMs = preferHoldMs,
                    ),
                )
            ) {
                DebugLog.i(TAG, "awaitUnderlyingReady ok fp=$fp prefer=$want elapsed=${elapsed}ms")
                return true
            }
            delay(250L)
        }
        val any = hasAnyUnderlyingInternet(context)
        DebugLog.w(
            TAG,
            "awaitUnderlyingReady timeout prefer=$want fp=${underlyingTransportFingerprint(context)} any=$any",
        )
        return OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReadyOnTimeout(any)
    }

    private fun hasUsableWifi(caps: NetworkCapabilities): Boolean {
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        }
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }
}
