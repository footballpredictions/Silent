package com.silent.vpn.policy

import org.junit.Assert.*
import org.junit.Test

class NetworkRecoveryQueueTest {
    @Test fun `capability callback cannot erase queued WiFi to LTE recovery`() {
        val queue = NetworkRecoveryQueue()
        queue.enqueue("transport_switch:mobile", 100L, 400L)
        queue.enqueue("capabilities:cell", 200L, 800L)
        assertEquals(300L, queue.remainingDelayMs(200L))
        assertEquals("transport_switch:mobile", queue.begin(500L)?.reason)
    }

    @Test fun `repeated callbacks cannot postpone an already queued recovery forever`() {
        val queue = NetworkRecoveryQueue()
        for (time in 1_000L..1_700L step 100L) queue.enqueue("cell_gap_restored", time, 800L)
        assertEquals("cell_gap_restored", queue.begin(1_800L)?.reason)
    }

    @Test fun `events during an awaited restart run once after the first operation finishes`() {
        val queue = NetworkRecoveryQueue()
        queue.enqueue("link_handover:cell", 1_000L, 0L)
        assertNotNull(queue.begin(1_000L))
        queue.enqueue("transport_switch:wifi", 2_000L, 400L)
        queue.enqueue("capabilities:wifi", 2_100L, 800L)
        assertNull(queue.begin(3_000L))
        queue.finish()
        assertEquals("transport_switch:wifi", queue.begin(3_000L)?.reason)
        queue.finish()
        assertNull(queue.remainingDelayMs(3_000L))
    }

    @Test fun `settle and transient failure retry retains strong event until accepted`() {
        val queue = NetworkRecoveryQueue()
        queue.enqueue("link_handover:cell", 1_000L, 0L)
        val first = requireNotNull(queue.begin(1_000L))
        queue.enqueue(NetworkRecoveryPolicy.retryReason(first.reason), 1_000L, 1_200L)
        queue.enqueue("capabilities:cell", 1_100L, 800L)
        queue.finish()
        assertEquals("link_handover:cell:retry", queue.begin(2_200L)?.reason)
        assertEquals("link_handover:cell:retry", NetworkRecoveryPolicy.retryReason("link_handover:cell:retry:suppressed:retry"))
    }

    @Test fun `disconnect clears queued reconnect and in flight state`() {
        val queue = NetworkRecoveryQueue()
        queue.enqueue("transport_switch:mobile", 0L, 400L)
        queue.begin(400L)
        queue.enqueue("internet_restored", 500L, 800L)
        queue.clear()
        assertFalse(queue.inFlight)
        assertNull(queue.begin(100_000L))
    }

    @Test fun `offline blackout queued before online return still grants wake before debounce`() {
        val queue = NetworkRecoveryQueue()
        assertFalse(queue.enqueue("underlying_blackout", 1_000L, 1_500L, allowWake = false))
        assertTrue(queue.enqueue("link_handover:cell", 2_000L, 800L, allowWake = true))
        assertEquals(62_000L, queue.wakeUntilMs)
        assertEquals("link_handover:cell", queue.begin(2_500L)?.reason)
        assertFalse(queue.enqueue("link_handover:cell:retry", 3_000L, 1_200L, allowWake = false))
        assertEquals(62_000L, queue.wakeUntilMs)
    }

    @Test fun `recovery retries cannot renew an exhausted wake budget`() {
        val queue = NetworkRecoveryQueue()
        assertTrue(queue.enqueue("cell_gap_restored", 1_000L, 0L, allowWake = true))
        queue.begin(1_000L)
        assertFalse(queue.enqueue("cell_gap_restored:retry", 62_000L, 0L, allowWake = false))
        assertFalse(queue.enqueue("internet_restored", 63_000L, 0L, allowWake = true))
        assertEquals(61_000L, queue.wakeUntilMs)
        queue.clear()
        assertTrue(queue.enqueue("cell_gap_restored", 64_000L, 0L, allowWake = true))
    }

    @Test fun `confirmed new radio outage grants a new bounded budget only when online event arrives`() {
        val queue = NetworkRecoveryQueue()
        assertTrue(queue.enqueue("link_handover:cell", 1_000L, 0L, allowWake = true))
        queue.begin(1_000L)
        queue.enqueue("link_handover:cell:retry", 62_000L, 0L, allowWake = false)
        queue.noteOffline()
        assertEquals(0L, queue.wakeUntilMs)
        assertFalse(queue.enqueue("link_handover:cell:retry", 70_000L, 0L, allowWake = false))
        assertTrue(queue.enqueue("cell_gap_restored", 80_000L, 800L, allowWake = true))
        assertEquals(140_000L, queue.wakeUntilMs)
    }
}
