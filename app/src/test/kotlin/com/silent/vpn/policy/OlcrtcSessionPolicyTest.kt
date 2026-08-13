package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Автотесты поломок Telemost↔WB: «нет сессии», heartbeat leave, leave по prefs.
 */
class OlcrtcSessionPolicyTest {

    private fun crypto64() = "a".repeat(64)

    private fun storeWithBoth(): OlcrtcSessionPolicy.SlotStore {
        val s = OlcrtcSessionPolicy.SlotStore()
        s.put(
            OlcrtcSessionPolicy.SlotStore.Slot(
                provider = "telemost",
                room = "https://telemost.yandex.ru/j/111",
                roomDbId = "101",
                cryptoKey = crypto64(),
            ),
        )
        s.put(
            OlcrtcSessionPolicy.SlotStore.Slot(
                provider = "wbstream",
                room = "wb-room-222",
                roomDbId = "202",
                cryptoKey = crypto64(),
            ),
        )
        return s
    }

    @Test
    fun `cache keys are per provider and never shared`() {
        assertEquals(
            "olcrtc_config_cache_v16_telemost",
            OlcrtcSessionPolicy.cacheKey("telemost"),
        )
        assertEquals(
            "olcrtc_config_cache_v16_wbstream",
            OlcrtcSessionPolicy.cacheKey("WBSTREAM"),
        )
        assertTrue(
            OlcrtcSessionPolicy.cacheKey("telemost") !=
                OlcrtcSessionPolicy.cacheKey("wbstream"),
        )
    }

    @Test
    fun `provider switch must not clear other slot`() {
        assertFalse(OlcrtcSessionPolicy.shouldClearCacheOnProviderSwitch())
        val store = storeWithBoth()
        val r = store.applyProviderSwitch("telemost", "wbstream")
        assertEquals("wbstream", r.selected)
        assertTrue(r.fromStillCached)
        assertTrue(r.toCached)
        assertFalse(r.missingSession)
        assertNotNull(store.get("telemost"))
        assertNotNull(store.get("wbstream"))
    }

    @Test
    fun `switch to empty slot reports missing session until prefetch`() {
        val store = OlcrtcSessionPolicy.SlotStore()
        store.put(
            OlcrtcSessionPolicy.SlotStore.Slot(
                provider = "telemost",
                room = "tm-1",
                roomDbId = "1",
                cryptoKey = crypto64(),
            ),
        )
        val r = store.applyProviderSwitch("telemost", "wbstream")
        assertTrue(r.missingSession)
        assertTrue(r.fromStillCached)
        // Prefetch fills WB without wiping TM
        store.put(
            OlcrtcSessionPolicy.SlotStore.Slot(
                provider = "wbstream",
                room = "wb-1",
                roomDbId = "2",
                cryptoKey = crypto64(),
            ),
        )
        assertFalse(store.applyProviderSwitch("telemost", "wbstream").missingSession)
        assertNotNull(store.get("telemost"))
    }

    @Test
    fun `heartbeat cancel must not leave room`() {
        assertFalse(OlcrtcSessionPolicy.shouldLeaveOnHeartbeatCancel())
        assertFalse(OlcrtcSessionPolicy.shouldStartHeartbeat(alreadyActive = true))
        assertTrue(OlcrtcSessionPolicy.shouldStartHeartbeat(alreadyActive = false))
    }

    @Test
    fun `double heartbeat start is no-op — regression for silent leave`() {
        // Was: start→cancel→finally leave while VPN green.
        var leaveCount = 0
        var loopActive = false
        fun startHeartbeat() {
            if (!OlcrtcSessionPolicy.shouldStartHeartbeat(loopActive)) return
            if (loopActive && OlcrtcSessionPolicy.shouldLeaveOnHeartbeatCancel()) {
                leaveCount++
            }
            loopActive = true
        }
        startHeartbeat()
        startHeartbeat() // tunnelReady + connect
        startHeartbeat()
        assertEquals(0, leaveCount)
        assertTrue(loopActive)
    }

    @Test
    fun `leave uses session snapshot not prefs after Apply`() {
        assertEquals(
            "telemost",
            OlcrtcSessionPolicy.resolveSessionProvider(
                sessionProvider = "telemost",
                prefsProvider = "wbstream",
            ),
        )
        val target = OlcrtcSessionPolicy.resolveLeaveTarget(
            sessionProvider = "telemost",
            sessionRoomDbId = "101",
            prefsProvider = "wbstream",
        )
        assertEquals("telemost", target.provider)
        assertEquals("101", target.roomDbId)
    }

    @Test
    fun `leave keeps both slots — dual-cache Apply`() {
        val store = storeWithBoth()
        // Баг старый: session=telemost, Apply→prefs=wb, leave() читал prefs → wipe WB.
        val buggyCleared = OlcrtcSessionPolicy.normalizeProvider("wbstream") // prefs
        val correct = OlcrtcSessionPolicy.resolveLeaveTarget(
            sessionProvider = "telemost",
            sessionRoomDbId = "101",
            prefsProvider = "wbstream",
        )
        assertTrue(buggyCleared != correct.provider)

        val leave = store.leave(sessionProvider = "telemost", prefsProvider = "wbstream")
        assertEquals("telemost", leave.cleared)
        assertFalse(leave.wipedUnrelated)
        // dual-cache: leave не стирает слоты — оба живы для Apply без bootstrap
        assertNotNull(store.get("telemost"))
        assertNotNull(store.get("wbstream"))
    }

    @Test
    fun `accept rejects denied empty and short crypto`() {
        assertFalse(
            OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = true,
                cryptoKeyLen = 32,
                providerEnabled = true,
                room = "r",
                denied = false,
                poolDenied = false,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = true,
                cryptoKeyLen = 64,
                providerEnabled = true,
                room = "",
                denied = false,
                poolDenied = false,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = true,
                cryptoKeyLen = 64,
                providerEnabled = true,
                room = "r",
                denied = true,
                poolDenied = false,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = false,
                cryptoKeyLen = 64,
                providerEnabled = true,
                room = "r",
                denied = false,
                poolDenied = false,
            ),
        )
        assertTrue(
            OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = true,
                cryptoKeyLen = 64,
                providerEnabled = true,
                room = "live-room",
                denied = false,
                poolDenied = false,
            ),
        )
    }

    @Test
    fun `denied assign must not overwrite good cache`() {
        val store = storeWithBoth()
        // Simulate reject: do not put
        val accept = OlcrtcSessionPolicy.shouldAcceptAssign(
            enabled = true,
            cryptoKeyLen = 64,
            providerEnabled = true,
            room = "",
            denied = true,
            poolDenied = true,
        )
        assertFalse(accept)
        assertNotNull(store.get("telemost"))
        assertNotNull(store.get("wbstream"))
    }

    @Test
    fun `leave keeps dual-cache slots`() {
        assertEquals(
            emptySet<String>(),
            OlcrtcSessionPolicy.cacheProvidersToClearOnLeave("telemost"),
        )
        assertEquals(
            emptySet<String>(),
            OlcrtcSessionPolicy.cacheProvidersToClearOnLeave("wbstream"),
        )
        assertEquals(
            setOf("telemost"),
            OlcrtcSessionPolicy.cacheProvidersToClearOnFailure("telemost"),
        )
        assertEquals(
            setOf("wbstream"),
            OlcrtcSessionPolicy.cacheProvidersToClearOnFailure("wbstream"),
        )
    }

    @Test
    fun `Apply cache-only when selected cached — pool keep like 160`() {
        assertFalse(OlcrtcSessionPolicy.shouldRevalidateSelectedOnApply(true))
        assertTrue(OlcrtcSessionPolicy.shouldRevalidateSelectedOnApply(false))
        assertTrue(
            OlcrtcSessionPolicy.shouldPreferCacheOnConnect(
                slotDirtyAfterLeave = true,
                hasCachedRoom = true,
            ),
        )
        assertTrue(
            OlcrtcSessionPolicy.shouldPreferCacheOnConnect(
                slotDirtyAfterLeave = false,
                hasCachedRoom = true,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldPreferCacheOnConnect(
                slotDirtyAfterLeave = false,
                hasCachedRoom = false,
            ),
        )
    }

    @Test
    fun `Apply while VPN up must stop before provider change`() {
        assertTrue(
            OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply(
                pendingProvider = "wbstream",
                currentProvider = "telemost",
                vpnOrTunnelRunning = true,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply(
                pendingProvider = "telemost",
                currentProvider = "telemost",
                vpnOrTunnelRunning = true,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply(
                pendingProvider = "wbstream",
                currentProvider = "telemost",
                vpnOrTunnelRunning = false,
            ),
        )
    }

    @Test
    fun `prefetch forces selected provider only`() {
        // Dual-cache: never force-refresh living slots (soft leave + sticky).
        assertFalse(OlcrtcSessionPolicy.shouldForcePrefetch("telemost", "telemost"))
        assertFalse(OlcrtcSessionPolicy.shouldForcePrefetch("wbstream", "telemost"))
        assertTrue(
            OlcrtcSessionPolicy.prefetchOk(
                force = true,
                hadCacheBefore = true,
                fetchedRoomNonBlank = true,
                hasCacheAfter = true,
            ),
        )
        // force fail but stale remains — Apply still has session (better than empty)
        assertTrue(
            OlcrtcSessionPolicy.prefetchOk(
                force = true,
                hadCacheBefore = true,
                fetchedRoomNonBlank = false,
                hasCacheAfter = true,
            ),
        )
        assertFalse(
            OlcrtcSessionPolicy.prefetchOk(
                force = true,
                hadCacheBefore = false,
                fetchedRoomNonBlank = false,
                hasCacheAfter = false,
            ),
        )
    }

    @Test
    fun `end to end Telemost to WB to Telemost without missing session`() {
        val store = storeWithBoth()
        // Connected telemost session
        var session = "telemost"
        var prefs = "telemost"

        // Apply WB while "running"
        assertTrue(
            OlcrtcSessionPolicy.shouldStopVpnBeforeProviderApply("wbstream", prefs, true),
        )
        // leave old session — dual-cache: оба слота остаются
        store.leave(sessionProvider = session, prefsProvider = "wbstream")
        assertNotNull(store.get("telemost"))
        assertNotNull(store.get("wbstream"))
        prefs = "wbstream"
        session = "wbstream"

        val sw = store.applyProviderSwitch("wbstream", "telemost")
        assertFalse(sw.missingSession)
        assertTrue(sw.fromStillCached)
        assertTrue(sw.toCached)
    }
}
