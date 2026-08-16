package com.silent.vpn.policy

/**
 * Silent (libclient/VK) должен обходить свой WG на основном VPN.
 * Иначе TURN/DTLS уходит в туннель и воркеры замирают на 2–3.
 * Bootstrap — наоборот, приложение внутри (логин через 10.66.66.1).
 */
object AppVpnExclusionPolicy {

    fun shouldExcludeApp(isBootstrap: Boolean, onMobileData: Boolean): Boolean {
        if (isBootstrap) return false
        return true
    }
}
