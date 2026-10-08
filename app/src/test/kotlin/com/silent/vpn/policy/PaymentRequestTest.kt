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
                PaymentRequest.retry { requests++; throw CancellationException("cancel") }
            }
            fail("must propagate cancellation")
        } catch (_: CancellationException) {
            assertEquals(1, requests)
        }
    }

    @Test
    fun `transient network failure can retry once inside the same deadline`() = runTest {
        var requests = 0
        val label = PaymentRequest.run {
            PaymentRequest.retry {
                if (++requests == 1) throw java.io.IOException("temporary")
                "label"
            }
        }
        assertEquals("label", label)
        assertEquals(2, requests)
    }
}
