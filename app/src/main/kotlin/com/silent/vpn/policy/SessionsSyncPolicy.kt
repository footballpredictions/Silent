package com.silent.vpn.policy

/**
 * Экран «Сессии»: живой /users/me на Wi‑Fi и на LTE.
 * Раньше LTE полностью пропускал poll — второй телефон не появлялся в списке.
 */
object SessionsSyncPolicy {
    fun shouldFetchLiveProfile(screenActive: Boolean): Boolean = screenActive

    fun <T> deviceListChanged(
        currentDevices: List<T>,
        currentCount: Int,
        incomingDevices: List<T>,
        incomingCount: Int,
    ): Boolean = currentDevices != incomingDevices || currentCount != incomingCount
}
