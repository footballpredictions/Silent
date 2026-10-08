package com.silent.vpn.policy

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.withTimeoutOrNull

internal object PaymentRequest {
    /** Includes tunnel/API/browser preparation, rather than a timeout per socket or retry. */
    suspend fun <T> run(timeoutMs: Long = 45_000L, block: suspend () -> T): T =
        withTimeoutOrNull(timeoutMs) { Result.success(block()) }?.getOrThrow()
            ?: error("Не удалось открыть оплату. Проверьте интернет и повторите.")

    suspend fun <T> retry(block: suspend () -> T): T {
        try {
            return block()
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            delay(400)
            return block()
        }
    }
}
