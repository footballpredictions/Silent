package com.silent.vpn.policy

/** Splash/тумблер: сначала публичный API (соты), Hive WG bootstrap только если соты молчат. */
object ConnectConfigFetchPolicy {
    fun skipPublicFailover(onMobile: Boolean, forLaunch: Boolean): Boolean {
        // Раньше splash (`forLaunch`) и LTE сразу шли в ephemeral на Улей :56000.
        // При блоке 443/WG анимация не поднимала временный интернет и не видела подписку.
        return false
    }
}
