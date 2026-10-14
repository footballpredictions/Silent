package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Test

class TransportLivenessWatchTest {
    @Test fun `frozen positive worker counters require consecutive awake observations`() {
        val watch = TransportLivenessWatch()
        assertEquals(TransportLivenessWatch.Action.VERIFY, watch.observe(1_000L, true, 100_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(1_000L, true, 104_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(1_000L, true, 110_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(1_000L, true, 118_000L))
        assertEquals(TransportLivenessWatch.Action.RECOVER, watch.observe(1_000L, true, 120_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(1_000L, true, 122_000L))
    }

    @Test fun `sleep between observations does not masquerade as a confirmed frozen process`() {
        val watch = TransportLivenessWatch()
        watch.observe(1_000L, true, 100_000L)
        assertEquals(TransportLivenessWatch.Action.VERIFY, watch.observe(1_000L, true, 200_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(201_000L, false, 201_000L))
    }

    @Test fun `fresh native heartbeat clears suspicion even on an idle zero traffic VPN`() {
        val watch = TransportLivenessWatch()
        watch.observe(1_000L, true, 100_000L)
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(104_000L, false, 104_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(109_000L, false, 109_000L))
    }

    @Test fun `normal ten second heartbeat after CPU sleep arrives before recovery is confirmed`() {
        val watch = TransportLivenessWatch()
        assertEquals(TransportLivenessWatch.Action.VERIFY, watch.observe(1_000L, true, 100_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(1_000L, true, 108_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(110_000L, false, 110_000L))
        assertEquals(TransportLivenessWatch.Action.NONE, watch.observe(110_000L, false, 112_000L))
    }
}
