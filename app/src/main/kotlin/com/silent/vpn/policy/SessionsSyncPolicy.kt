package com.silent.vpn.policy

/**
 * Экран «Сессии»: живой /users/me на Wi‑Fi и на LTE.
 * Раньше LTE полностью пропускал poll — второй телефон не появлялся в списке.
 */
object SessionsSyncPolicy {
    fun shouldFetchLiveProfile(screenActive: Boolean): Boolean = screenActive

    fun useTunnelProfileFetch(onMobileData: Boolean, mainVpnUp: Boolean): Boolean =
        onMobileData && mainVpnUp

    fun deviceListChanged(
        currentIds: Set<String>,
        currentCount: Int,
        incomingIds: Set<String>,
        incomingCount: Int,
    ): Boolean = currentIds != incomingIds || currentCount != incomingCount
}
