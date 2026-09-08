package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GoogleAuthTunnelPolicyTest {

    @Test
    fun `chrome and play services cannot leave the tunnel without the ai app`() {
        val user = setOf(
            "com.android.chrome",
            "com.google.android.gms",
            "org.telegram.messenger",
        )
        assertEquals(
            setOf("org.telegram.messenger"),
            GoogleAuthTunnelPolicy.excludeWithoutGoogleAuth(user),
        )
        assertEquals(
            setOf("com.android.chrome", "com.google.android.gms"),
            GoogleAuthTunnelPolicy.droppedFromExclude(user),
        )
    }

    @Test
    fun `vk packages are still allowed outside the tunnel`() {
        val vk = setOf("com.vkontakte.android", "com.vk.calls")
        assertEquals(vk, GoogleAuthTunnelPolicy.excludeWithoutGoogleAuth(vk))
        assertTrue(GoogleAuthTunnelPolicy.droppedFromExclude(vk).isEmpty())
    }

    @Test
    fun `webview stays with the apps so oauth custom tabs share one ip`() {
        assertTrue("com.google.android.webview" in GoogleAuthTunnelPolicy.MUST_STAY_IN_TUNNEL)
        assertTrue("com.android.chrome" in GoogleAuthTunnelPolicy.MUST_STAY_IN_TUNNEL)
        assertTrue("com.google.android.gms" in GoogleAuthTunnelPolicy.MUST_STAY_IN_TUNNEL)
    }
}
