package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppExclusionsPersistTest {

    @Test
    fun `switch mode does not wipe the other list`() {
        var state = AppExclusionsPersist.hydrate(
            selectedIds = emptySet(),
            whitelist = false,
        )
        state = AppExclusionsPersist.setActive(state.copy(whitelist = true), setOf("A", "B"))
        state = AppExclusionsPersist.switchMode(state, toWhitelist = false)
        state = AppExclusionsPersist.setActive(state, setOf("C", "D", "E"))
        state = AppExclusionsPersist.switchMode(state, toWhitelist = true)

        assertTrue(state.whitelist)
        assertEquals(setOf("A", "B"), state.whitelistAppIds)
        assertEquals(setOf("C", "D", "E"), state.blacklistAppIds)
        assertEquals(setOf("A", "B"), state.activeIds)
        assertEquals("whitelist", state.appBypassMode)
    }

    @Test
    fun `hydrate after restart keeps blacklist mode and both lists`() {
        val saved = AppExclusionsPersist.State(
            whitelist = false,
            blacklistAppIds = setOf("C", "D", "E"),
            whitelistAppIds = setOf("A", "B"),
        )
        val reloaded = AppExclusionsPersist.hydrate(
            selectedIds = saved.activeIds,
            whitelist = saved.whitelist,
            blacklistAppIds = saved.blacklistAppIds,
            whitelistAppIds = saved.whitelistAppIds,
        )
        assertFalse(reloaded.whitelist)
        assertEquals("blacklist", reloaded.appBypassMode)
        assertEquals(setOf("C", "D", "E"), reloaded.blacklistAppIds)
        assertEquals(setOf("A", "B"), reloaded.whitelistAppIds)
    }

    @Test
    fun `hydrate after restart keeps whitelist mode and selections`() {
        val reloaded = AppExclusionsPersist.hydrate(
            selectedIds = setOf("maps"),
            whitelist = true,
            blacklistAppIds = setOf("game"),
            whitelistAppIds = setOf("maps", "chrome"),
        )
        assertTrue(reloaded.whitelist)
        assertEquals(setOf("maps", "chrome"), reloaded.whitelistAppIds)
        assertEquals(setOf("game"), reloaded.blacklistAppIds)
        assertEquals(setOf("maps", "chrome"), reloaded.activeIds)
    }

    @Test
    fun `legacy single list migrates into the then-active mode`() {
        val black = AppExclusionsPersist.hydrate(
            selectedIds = setOf("chrome"),
            whitelist = false,
        )
        assertEquals(setOf("chrome"), black.blacklistAppIds)
        assertEquals(emptySet<String>(), black.whitelistAppIds)

        val white = AppExclusionsPersist.hydrate(
            selectedIds = setOf("maps"),
            whitelist = true,
        )
        assertEquals(emptySet<String>(), white.blacklistAppIds)
        assertEquals(setOf("maps"), white.whitelistAppIds)
        assertTrue(white.whitelist)
    }

    @Test
    fun `empty whitelist tunnel intent is fail-safe all through VPN`() {
        val emptyWl = AppExclusionsPersist.State(
            whitelist = true,
            blacklistAppIds = setOf("C"),
            whitelistAppIds = emptySet(),
        )
        val intent = AppExclusionsPersist.tunnelIntent(emptyWl)
        assertFalse(intent.whitelist)
        assertEquals(emptySet<String>(), intent.userPackages)
    }

    @Test
    fun `non-empty whitelist tunnel intent keeps whitelist apps for UI mode`() {
        val state = AppExclusionsPersist.State(
            whitelist = true,
            blacklistAppIds = setOf("C"),
            whitelistAppIds = setOf("A", "B"),
        )
        val intent = AppExclusionsPersist.tunnelIntent(state)
        assertTrue(intent.whitelist)
        assertEquals(setOf("A", "B"), intent.userPackages)
    }
}
