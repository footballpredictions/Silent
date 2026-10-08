package com.silent.vpn.policy

import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext

/** A payment owns a temporary tunnel, and returns the previously selected main tunnel once. */
internal class PaymentVpnHandoff<T>(
    initialSnapshot: T? = null,
    private val saveSnapshot: (T?) -> Unit = {},
) {
    private var snapshot: T? = initialSnapshot
    private var generation = 0

    val hasMainToRestore: Boolean get() = snapshot != null

    suspend fun prepare(
        mainActive: Boolean,
        captureMain: () -> T?,
        startPayment: suspend () -> Boolean,
    ): Boolean {
        if (mainActive && snapshot == null) {
            val saved = captureMain() ?: error("Не удалось сохранить основной VPN. Переподключите VPN и повторите оплату.")
            snapshot = saved
            saveSnapshot(saved)
        }
        return startPayment()
    }

    /** Caller serializes prepare/finish. Explicit connect/disconnect may revoke restoration. */
    suspend fun finish(
        stopPayment: suspend () -> Unit,
        restoreMain: suspend (T, stillWanted: () -> Boolean) -> Unit,
    ) = withContext(NonCancellable) {
        val ticket = generation
        stopPayment()
        if (ticket != generation) return@withContext
        val saved = snapshot ?: return@withContext
        snapshot = null
        saveSnapshot(null)
        restoreMain(saved) { generation == ticket }
    }

    fun discard() {
        generation++
        snapshot = null
        saveSnapshot(null)
    }
}
