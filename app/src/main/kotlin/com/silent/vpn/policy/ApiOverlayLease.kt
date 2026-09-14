package com.silent.vpn.policy

/**
 * Счётчик вложенных API-overlay на bootstrap VPN.
 *
 * Старый `withApiOverlay`: если overlay уже включён, дочерний блок шёл без аренды,
 * а родитель в `finally` выключал маршрут. Poll QR на ТВ стартовал изнутри `qrStart`
 * и дальше ходил на 10.66.66.1 уже вне туннеля — телефон успевал подтвердить, ТВ нет.
 */
object ApiOverlayLease {
    data class State(val active: Boolean = false, val depth: Int = 0)

    fun begin(state: State): Pair<State, Boolean> {
        val hardwareEnter = !state.active
        return State(active = true, depth = state.depth + 1) to hardwareEnter
    }

    fun end(state: State): Pair<State, Boolean> {
        val depth = (state.depth - 1).coerceAtLeast(0)
        val hardwareRestore = depth == 0 && state.active
        return State(active = if (hardwareRestore) false else state.active, depth = depth) to hardwareRestore
    }
}
