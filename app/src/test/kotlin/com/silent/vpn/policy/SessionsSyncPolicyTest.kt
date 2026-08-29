package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionsSyncPolicyTest {

    @Test
    fun `sessions screen polls on lte too`() {
        assertTrue(SessionsSyncPolicy.shouldFetchLiveProfile(true))
        assertFalse(SessionsSyncPolicy.shouldFetchLiveProfile(false))
        assertTrue(SessionsSyncPolicy.useTunnelProfileFetch(onMobileData = true, mainVpnUp = true))
        assertFalse(SessionsSyncPolicy.useTunnelProfileFetch(onMobileData = true, mainVpnUp = false))
    }

    @Test
    fun `device list change is detected`() {
        assertTrue(
            SessionsSyncPolicy.deviceListChanged(
                currentIds = setOf("a"),
                currentCount = 1,
                incomingIds = setOf("a", "b"),
                incomingCount = 2,
            ),
        )
        assertFalse(
            SessionsSyncPolicy.deviceListChanged(
                currentIds = setOf("a"),
                currentCount = 1,
                incomingIds = setOf("a"),
                incomingCount = 1,
            ),
        )
    }
}
