package com.silent.vpn.policy

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class PaymentProfileRefreshTest {
    private data class Profile(val active: Boolean, val devices: Int)

    @Test
    fun `success and VPN teardown wait for fresh profile and cache application`() = runTest {
        val response = CompletableDeferred<Profile>()
        val events = mutableListOf<String>()
        var ui = Profile(false, 3)
        var cache = ui
        launch {
            val synced = refreshPaidPaymentProfile(
                fetch = { events += "fetch-through-payment-overlay"; response.await() },
                isPaid = { it.active },
                apply = { cache = it; ui = it; events += "apply" },
            )
            if (synced) { events += "success"; events += "stop-payment-vpn" }
        }
        runCurrent()
        assertEquals(listOf("fetch-through-payment-overlay"), events)
        assertFalse(ui.active)
        response.complete(Profile(true, 5))
        runCurrent()
        assertEquals(Profile(true, 5), ui)
        assertEquals(ui, cache)
        assertEquals(listOf("fetch-through-payment-overlay", "apply", "success", "stop-payment-vpn"), events)
    }

    @Test
    fun `inactive profile keeps the payment route and retries without publishing success`() = runTest {
        var applied = false
        assertFalse(refreshPaidPaymentProfile({ Profile(false, 3) }, { it.active }, { applied = true }))
        assertFalse(applied)
        assertTrue(refreshPaidPaymentProfile({ Profile(true, 5) }, { it.active }, { applied = true }))
        assertTrue(applied)
    }

    @Test
    fun `failed request never falls back to cached paid profile`() = runTest {
        var applied = false
        try {
            refreshPaidPaymentProfile<Profile>({ error("network") }, { it.active }, { applied = true })
            fail("network failure must remain retryable")
        } catch (_: IllegalStateException) {
            assertFalse(applied)
        }
    }
}
