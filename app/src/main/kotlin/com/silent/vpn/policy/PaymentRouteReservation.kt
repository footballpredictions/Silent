package com.silent.vpn.policy

/** Read-only preparation can be reused for confirmation, never across identity/path changes. */
internal class PaymentRouteReservation<K, V>(private val clock: () -> Long, private val lifetimeMs: Long = 60_000) {
    private var key: K? = null
    private var value: V? = null
    private var preparedAt = 0L

    fun remember(key: K, value: V) {
        this.key = key
        this.value = value
        preparedAt = clock()
    }

    fun get(key: K): V? = value?.takeIf {
        this.key == key && clock() - preparedAt in 0 until lifetimeMs
    }

    fun clear() { key = null; value = null }
}
