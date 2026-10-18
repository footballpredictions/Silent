package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionsSyncPolicyTest {

    @Test
    fun `sessions screen polls on lte too`() {
        assertTrue(SessionsSyncPolicy.shouldFetchLiveProfile(true))
        assertFalse(SessionsSyncPolicy.shouldFetchLiveProfile(false))
    }

    @Test
    fun `device list change is detected`() {
        assertTrue(
            SessionsSyncPolicy.deviceListChanged(
                currentDevices = listOf("a"),
                currentCount = 1,
                incomingDevices = listOf("a", "b"),
                incomingCount = 2,
            ),
        )
        assertFalse(
            SessionsSyncPolicy.deviceListChanged(
                currentDevices = listOf("a"),
                currentCount = 1,
                incomingDevices = listOf("a"),
                incomingCount = 1,
            ),
        )
    }

    @Test
    fun `online and name changes are detected without adding devices`() {
        data class Session(val id: String, val name: String, val online: Boolean)
        val old = Session("a", "Phone", false)
        assertTrue(SessionsSyncPolicy.deviceListChanged(listOf(old), 1, listOf(old.copy(online = true)), 1))
        assertTrue(SessionsSyncPolicy.deviceListChanged(listOf(old), 1, listOf(old.copy(name = "TV")), 1))
    }
}
