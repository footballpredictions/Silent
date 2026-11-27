package com.silent.vpn.policy

import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class PaymentRouteSessionTest {
    @Test fun `checkout reserves one full route when the direct or split path only loads the page shell`() = runTest {
        for ((main, split) in listOf(false to false, false to true, true to true, true to false)) {
            val session = PaymentRouteSession<String, String, String>({ 0 })
            val current = if (main) "main" else "public"
            val currentBases = listOf(current).filter {
                PaymentTunnelPolicy.canReuseBrowserPath(main, nativeMain = main, splitBrowserRoute = split)
            }
            var temporaryStarts = 0
            suspend fun prepare() = session.prepare({ "account-plan-network" }, { true }, currentBases, { true }, { it },
                { "preview" }, { temporaryStarts++; "full-temporary" to "preview" })
            val route = prepare()
            assertEquals("main=$main, split=$split", if (main && !split) "main" else "full-temporary", route.api)
            assertSame(route, prepare())
            assertEquals(if (main && !split) 0 else 1, temporaryStarts)
        }
    }

    @Test fun `working main VPN is retained and preview init browser share one preparation`() = runTest {
        val session = PaymentRouteSession<String, String, String>({ 0 })
        var probes = 0; var previews = 0; var inits = 0
        suspend fun prepare() = session.prepare({ "main-account-plan" }, { true }, listOf("native-main"),
            { probes++; true }, { it }, { previews++; "price" }, { error("working main must remain") })
        val preview = prepare()
        val confirm = prepare()
        assertSame(preview, confirm)
        PaymentRequest.create { inits++; assertEquals("native-main", confirm.api) }
        assertSame(confirm, prepare()) // browser/return does not prepare another route
        assertEquals(1, probes); assertEquals(1, previews); assertEquals(1, inits)
    }

    @Test fun `site alone cannot approve direct route and temporary exits share one VPN`() = runTest {
        val session = PaymentRouteSession<String, String, String>({ 0 })
        val exits = listOf(BootstrapOverlayEndpoint("1.2.3.4", 56000, false), BootstrapOverlayEndpoint("2.3.4.5", 56000, false))
        val failover = PaymentRouteFailover()
        val handoff = PaymentVpnHandoff<String>()
        var vpnStarts = 0; var switches = 0; var stops = 0; var current = exits[0]; var identity = "direct"
        suspend fun prepare() = session.prepare({ identity }, { true }, listOf("public"), { true }, { it },
            { throw IOException("public API blocked") }, {
                assertTrue(handoff.prepare(false, { null }) {
                    failover.prepare(exits, { exit, _ ->
                        if (vpnStarts == 0) vpnStarts++ else switches++
                        current = exit; identity = "temporary-${exit.ip}"; true
                    }, { current == exits[1] }, { stops++ })
                })
                "temporary" to "price"
            })
        assertEquals("temporary", prepare().api)
        assertEquals("temporary", prepare().api)
        assertEquals(1, vpnStarts); assertEquals(1, switches); assertEquals(0, stops)
        handoff.finish({ stops++ }, { _, _ -> error("no original main") })
        assertEquals(1, stops)
    }

    @Test fun `changed network account plan expired reservation require fresh read-only preparation`() = runTest {
        var now = 0L; var identity = "first"; var reads = 0
        val session = PaymentRouteSession<String, String, String>({ now })
        suspend fun prepare() = session.prepare({ identity }, { true }, listOf("public"), { true }, { it },
            { reads++; "price" }, { error("unneeded VPN") })
        prepare(); prepare(); assertEquals(1, reads)
        identity = "different-network"; prepare(); assertEquals(2, reads)
        identity = "different-account-plan"; prepare(); assertEquals(3, reads)
        now = 60_000; prepare(); assertEquals(4, reads)
        session.clear(); prepare(); assertEquals(5, reads)
    }

    @Test fun `manual VPN change during probe never starts payment over the new owner`() = runTest {
        var owned = true
        val session = PaymentRouteSession<String, String, String>({ 0 })
        try {
            session.prepare({ "same" }, { owned }, listOf("public"), { owned = false; false }, { it },
                { "price" }, { error("must not replace new VPN") })
            fail("must reject stale attempt")
        } catch (_: IllegalStateException) { }
    }

    @Test fun `account rejection and cancellation cannot trigger route failover`() = runTest {
        for (failure in listOf(PaymentApiRejection("session expired"), CancellationException("cancel"))) {
            val session = PaymentRouteSession<String, String, String>({ 0 })
            try {
                session.prepare({ "same" }, { true }, listOf("public", "alternate"), { true }, { it },
                    { throw failure }, { error("cannot switch for account errors or cancellation") })
                fail("must propagate")
            } catch (received: Exception) { assertSame(failure, received) }
        }
    }
}
