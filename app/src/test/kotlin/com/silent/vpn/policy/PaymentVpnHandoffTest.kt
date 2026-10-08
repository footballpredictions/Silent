package com.silent.vpn.policy

import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class PaymentVpnHandoffTest {
    @Test
    fun `main VPN is saved before switching and restored once after payment ends`() = runTest {
        val events = mutableListOf<String>()
        var disk: String? = null
        val handoff = PaymentVpnHandoff<String>(saveSnapshot = { disk = it })
        assertTrue(handoff.prepare(true, { events += "capture"; "server3" }) {
            assertEquals("server3", disk)
            events += "payment-vpn"
            true
        })
        suspend fun finish() = handoff.finish(
            stopPayment = { events += "stop-payment" },
            restoreMain = { config, wanted -> assertTrue(wanted()); events += "restore-$config" },
        )
        finish()
        finish()
        assertEquals(listOf("capture", "payment-vpn", "stop-payment", "restore-server3", "stop-payment"), events)
        assertNull(disk)
    }

    @Test
    fun `payment started with VPN off does not invent a main connection`() = runTest {
        val handoff = PaymentVpnHandoff<String>()
        handoff.prepare(false, { error("no main") }) { true }
        handoff.finish({}, { _, _ -> error("must remain off") })
    }

    @Test
    fun `failed startup and retry retain original server for restoration`() = runTest {
        val handoff = PaymentVpnHandoff<String>()
        assertFalse(handoff.prepare(true, { "server3" }) { false })
        assertTrue(handoff.prepare(false, { error("already stopped") }) { true })
        handoff.finish({}, { config, _ -> assertEquals("server3", config) })
    }

    @Test
    fun `main is not stopped when its configuration cannot be saved`() = runTest {
        var started = false
        try {
            PaymentVpnHandoff<String>().prepare(true, { null }) { started = true; true }
            fail("missing snapshot")
        } catch (_: IllegalStateException) {
            assertFalse(started)
        }
    }

    @Test
    fun `cancelled payment cleanup still restores main VPN`() = runTest {
        val handoff = PaymentVpnHandoff<String>()
        handoff.prepare(true, { "server3" }) { true }
        var restored = false
        val cleanup = launch {
            handoff.finish({ delay(1_000) }, { _, _ -> delay(1_000); restored = true })
        }
        runCurrent()
        cleanup.cancelAndJoin()
        assertTrue(restored)
    }

    @Test
    fun `manual disconnect while stopping payment prevents automatic reconnect`() = runTest {
        val handoff = PaymentVpnHandoff<String>()
        handoff.prepare(true, { "server3" }) { true }
        val cleanup = launch {
            handoff.finish({ delay(1_000) }, { _, _ -> error("user disconnected") })
        }
        runCurrent()
        handoff.discard()
        cleanup.join()
        assertFalse(handoff.hasMainToRestore)
    }

    @Test
    fun `manual action during restoration revokes the completion callback`() = runTest {
        val handoff = PaymentVpnHandoff<String>("server3")
        var completed = false
        val cleanup = launch {
            handoff.finish({}, { _, wanted -> delay(1_000); completed = wanted() })
        }
        runCurrent()
        handoff.discard()
        cleanup.join()
        assertFalse(completed)
    }

    @Test
    fun `saved intent survives recreation while payment is in browser`() = runTest {
        var disk: String? = null
        PaymentVpnHandoff<String>(saveSnapshot = { disk = it })
            .prepare(true, { "server3" }) { true }
        var restored: String? = null
        PaymentVpnHandoff(disk, saveSnapshot = { disk = it })
            .finish({}, { config, _ -> restored = config })
        assertEquals("server3", restored)
        assertNull(disk)
    }
}
