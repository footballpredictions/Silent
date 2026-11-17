package com.silent.vpn.policy

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class PaymentRequestTest {
    @Test
    fun `stalled tunnel preparation clears opening attempt with a user error`() = runTest {
        try {
            PaymentRequest.run(timeoutMs = 1_000) { awaitCancellation() }
            fail("must not spin forever")
        } catch (e: IllegalStateException) {
            assertTrue(e.message.orEmpty().contains("Повторите", ignoreCase = true))
        }
    }

    @Test
    fun `cancelling payment never creates another payment label`() = runTest {
        var requests = 0
        try {
            PaymentRequest.run {
                PaymentRequest.create { requests++; throw CancellationException("cancel") }
            }
            fail("must propagate cancellation")
        } catch (_: CancellationException) {
            assertEquals(1, requests)
        }
    }

    @Test
    fun `network failure never replays payment creation`() = runTest {
        var requests = 0
        try {
            PaymentRequest.run { PaymentRequest.create { requests++; throw java.io.IOException("timeout after send") } }
            fail("must propagate failure")
        } catch (_: java.io.IOException) { assertEquals(1, requests) }
    }
}
