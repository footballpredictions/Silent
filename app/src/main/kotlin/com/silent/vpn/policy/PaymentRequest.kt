package com.silent.vpn.policy

import kotlinx.coroutines.withTimeoutOrNull

internal object PaymentRequest {
    /** Includes tunnel/API/browser preparation, rather than a timeout per socket or retry. */
    suspend fun <T> run(timeoutMs: Long = 45_000L, block: suspend () -> T): T =
        withTimeoutOrNull(timeoutMs) { Result.success(block()) }?.getOrThrow()
            ?: error("Не удалось открыть оплату. Проверьте интернет и повторите.")

    /** A timed-out POST may already have created a payment. Never replay it. */
    suspend fun <T> create(block: suspend () -> T): T = block()
}
