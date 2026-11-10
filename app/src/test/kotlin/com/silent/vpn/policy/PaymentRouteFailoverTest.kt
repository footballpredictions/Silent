package com.silent.vpn.policy

import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class PaymentRouteFailoverTest {
    private val first = BootstrapOverlayEndpoint("87.58.213.193", 56000, false)
    private val second = BootstrapOverlayEndpoint("78.17.74.27", 56000, false)
    private val third = BootstrapOverlayEndpoint("89.37.192.241", 56000, false)

    @Test fun `API ready but payment HTTPS fails - try next exit`() = runTest {
        val router = PaymentRouteFailover()
        val events = mutableListOf<String>()
        var exit = first
        val ready = router.prepare(listOf(first, second), start = { route, _ ->
            exit = route; events += "start:${route.ip}"; true
        }, probe = { events += "https:${exit.ip}"; exit == second }, stop = { events += "stop:${it.ip}" })
        assertTrue(ready)
        assertEquals(second, router.selected)
        assertEquals(listOf("start:${first.ip}", "https:${first.ip}", "stop:${first.ip}",
            "start:${second.ip}", "https:${second.ip}"), events)
    }

    @Test fun `can try a third exit without loops or duplicate candidates`() = runTest {
        val router = PaymentRouteFailover()
        val starts = mutableListOf<BootstrapOverlayEndpoint>()
        var current = first
        assertTrue(router.prepare(listOf(first, first, second, third), { route, _ ->
            starts += route; current = route; true
        }, { current == third }, {}))
        assertEquals(listOf(first, second, third), starts)
    }

    @Test fun `all routes failed - no selected server remains`() = runTest {
        val router = PaymentRouteFailover()
        var starts = 0; var probes = 0; var stopped = 0
        val ready = router.prepare(listOf(first, second), { _, _ -> starts++; true }, { probes++; false }, { stopped++ })
        assertFalse(ready); assertNull(router.selected)
        assertEquals(2, starts); assertEquals(2, probes); assertEquals(2, stopped)
    }

    @Test fun `successful current exit is reused and rechecked`() = runTest {
        val router = PaymentRouteFailover()
        var current = first
        assertTrue(router.prepare(listOf(first, second), { route, _ -> current = route; true }, { current == second }, {}))
        val attempts = mutableListOf<Pair<BootstrapOverlayEndpoint, Boolean>>()
        assertTrue(router.prepare(listOf(first, second), { route, reuse -> attempts += route to reuse; true }, { true }, {}))
        assertEquals(listOf(second to true), attempts)
    }

    @Test fun `chosen exit later fails - move to another exit`() = runTest {
        val router = PaymentRouteFailover()
        var current = first
        assertTrue(router.prepare(listOf(first, second), { route, _ -> current = route; true }, { true }, {}))
        assertTrue(router.prepare(listOf(first, second), { route, _ -> current = route; true }, { current == second }, {}))
        assertEquals(second, router.selected)
    }

    @Test fun `attempt timeout stops failed route then tries next`() = runTest {
        val router = PaymentRouteFailover(attemptTimeoutMs = 100)
        val stopped = mutableListOf<BootstrapOverlayEndpoint>()
        assertTrue(router.prepare(listOf(first, second), { route, _ ->
            if (route == first) delay(1_000)
            true
        }, { true }, { stopped += it }))
        assertEquals(listOf(first), stopped); assertEquals(second, router.selected)
    }

    @Test fun `cancellation never starts another server`() = runTest {
        val router = PaymentRouteFailover()
        var starts = 0; var stops = 0
        val job = launch { router.prepare(listOf(first, second), { _, _ -> starts++; true }, { delay(10_000); true }, { stops++ }) }
        runCurrent(); job.cancelAndJoin()
        assertEquals(1, starts); assertEquals(1, stops); assertNull(router.selected)
    }

    @Test fun `manual VPN action revokes stale attempt without stopping new owner`() = runTest {
        val router = PaymentRouteFailover()
        var starts = 0; var stops = 0
        val job = launch { assertFalse(router.prepare(listOf(first, second), { _, _ -> starts++; true }, {
            delay(100); true
        }, { stops++ })) }
        runCurrent(); router.clear(); job.join()
        assertEquals(1, starts); assertEquals(0, stops); assertNull(router.selected)
    }

    @Test fun `failed exit followed by successful payment restores original main once`() = runTest {
        val router = PaymentRouteFailover()
        val handoff = PaymentVpnHandoff<String>()
        var current = first; val restored = mutableListOf<String>()
        assertTrue(handoff.prepare(true, { "original-main-server" }) {
            router.prepare(listOf(first, second), { route, _ -> current = route; true }, { current == second }, {})
        })
        repeat(2) { handoff.finish({ router.clear() }, { saved, _ -> restored += saved }) }
        assertEquals(listOf("original-main-server"), restored)
    }

    @Test fun `manual connect cancels payment without stopping or restoring over the new VPN`() = runTest {
        val router = PaymentRouteFailover()
        val handoff = PaymentVpnHandoff<String>()
        var starts = 0; var stops = 0; var restores = 0
        val job = launch {
            handoff.prepare(true, { "previous-main" }) {
                router.prepare(listOf(first, second), { _, _ -> starts++; true }, {
                    delay(10_000); true
                }, { stops++ })
            }
        }
        runCurrent()
        handoff.discard()
        router.clear()
        job.cancelAndJoin()
        handoff.finish({}, { _, _ -> restores++ })
        assertEquals(1, starts)
        assertEquals(0, stops)
        assertEquals(0, restores)
    }

    @Test fun `all exits unavailable still restores the saved main after payment cleanup`() = runTest {
        val router = PaymentRouteFailover()
        val handoff = PaymentVpnHandoff<String>()
        val restored = mutableListOf<String>()
        assertFalse(handoff.prepare(true, { "previous-main" }) {
            router.prepare(listOf(first, second), { _, _ -> false }, {
                fail("HTTPS cannot run before the tunnel is ready"); true
            }, {})
        })
        handoff.finish({ router.clear() }, { saved, _ -> restored += saved })
        assertEquals(listOf("previous-main"), restored)
    }

    @Test fun `candidate list preserves normal cells and hive fallback without AI or invalid IPs`() {
        val got = PaymentRouteFailover.candidates("89.125.188.100", 56000,
            listOf(first.ip, second.ip, first.ip, "192.177.26.38", "localhost", "89.125.188.100"))
        assertEquals(listOf(first.ip, second.ip, "89.125.188.100"), got.map { it.ip })
        assertTrue(got.last().isHive)
    }
}
