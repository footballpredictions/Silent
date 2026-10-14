package com.silent.vpn.policy

import org.junit.Assert.*
import org.junit.Test

class UnderlyingRecoveryTrackerTest {
    private fun state(id: String, transport: String, internet: Boolean = true, validated: Boolean = true) =
        UnderlyingRecoveryTracker.NetworkState(id, transport, internet, validated)

    @Test fun `abrupt onLost without onLosing remembers which network was selected`() {
        val tracker = UnderlyingRecoveryTracker()
        tracker.capabilities(state("cellA", "cell"))
        assertEquals("cellA", tracker.selected()?.id)
        assertTrue(tracker.lost("cellA"))
        assertNull(tracker.selected())
        tracker.capabilities(state("cellB", "cell", validated = false))
        assertEquals("cellB", tracker.selected()?.id)
        assertTrue(tracker.selected()?.internet == true)
    }

    @Test fun `same transport new Network is visible even when new available precedes old lost`() {
        val tracker = UnderlyingRecoveryTracker()
        tracker.capabilities(state("cellA", "cell"))
        assertEquals("cellA", tracker.selected()?.id)
        tracker.capabilities(state("cellB", "cell"))
        assertEquals("cellA", tracker.selected()?.id)
        assertTrue(tracker.lost("cellA"))
        assertEquals("cellB", tracker.selected()?.id)
    }

    @Test fun `background cellular loss and address changes cannot evict a live WiFi`() {
        val tracker = UnderlyingRecoveryTracker()
        tracker.capabilities(state("wifiA", "wifi"))
        tracker.capabilities(state("cellA", "cell"))
        tracker.linkChanged("cellA", "10.0.0.1")
        assertTrue(tracker.linkChanged("cellA", "10.0.0.2"))
        assertEquals("wifiA", tracker.selected()?.id)
        assertFalse(tracker.lost("cellA"))
        assertEquals("wifiA", tracker.selected()?.id)
    }

    @Test fun `same Network actual IP changes remain visible inside thirty seconds`() {
        val tracker = UnderlyingRecoveryTracker()
        tracker.capabilities(state("cellA", "cell"))
        assertFalse(tracker.linkChanged("cellA", "10.0.0.1"))
        assertTrue(tracker.linkChanged("cellA", "10.0.0.2"))
        assertFalse(tracker.linkChanged("cellA", "10.0.0.2"))
        assertTrue(tracker.linkChanged("cellA", "10.0.0.3"))
    }

    @Test fun `link properties before capabilities build a baseline without a synchronous query`() {
        val tracker = UnderlyingRecoveryTracker()
        assertFalse(tracker.linkChanged("cellA", "10.0.0.1"))
        assertNull(tracker.selected())
        tracker.capabilities(state("cellA", "cell"))
        assertTrue(tracker.linkChanged("cellA", "10.0.0.2"))
        assertEquals("cellA", tracker.selected()?.id)
    }

    @Test fun `INTERNET loss is kept even though the callback request no longer matches`() {
        val tracker = UnderlyingRecoveryTracker()
        tracker.capabilities(state("cellA", "cell"))
        tracker.capabilities(state("cellA", "cell", internet = false, validated = false))
        assertNull(tracker.selected())
        tracker.capabilities(state("cellA", "cell", validated = false))
        assertEquals("cellA", tracker.selected()?.id)
    }

    @Test fun `VALIDATED only WiFi blip does not switch to a background cell and back`() {
        var now = 1_000L
        val tracker = UnderlyingRecoveryTracker { now }
        tracker.capabilities(state("wifiA", "wifi"))
        tracker.capabilities(state("cellA", "cell"))
        assertEquals("wifiA", tracker.selected()?.id)
        tracker.capabilities(state("wifiA", "wifi", validated = false))
        now += 1_000L
        assertEquals("wifiA", tracker.selected()?.id)
        tracker.capabilities(state("wifiA", "wifi"))
        assertEquals("wifiA", tracker.selected()?.id)
        tracker.capabilities(state("wifiA", "wifi", internet = false, validated = false))
        assertEquals("cellA", tracker.selected()?.id)
    }

    @Test fun `sustained WiFi WAN validation loss hands over to an available cell`() {
        var now = 1_000L
        val tracker = UnderlyingRecoveryTracker { now }
        tracker.capabilities(state("wifiA", "wifi"))
        tracker.capabilities(state("cellA", "cell"))
        assertEquals("wifiA", tracker.selected()?.id)
        tracker.capabilities(state("wifiA", "wifi", validated = false))
        now += 1_000L
        assertEquals("wifiA", tracker.selected()?.id)
        now += 3_000L
        assertEquals("cellA", tracker.selected()?.id)
        tracker.capabilities(state("wifiA", "wifi"))
        assertEquals("wifiA", tracker.selected()?.id)
    }
}
