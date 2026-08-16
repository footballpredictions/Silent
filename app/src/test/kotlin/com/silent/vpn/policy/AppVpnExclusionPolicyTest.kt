package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppVpnExclusionPolicyTest {

    @Test
    fun `bootstrap keeps app in tunnel`() {
        assertFalse(AppVpnExclusionPolicy.shouldExcludeApp(isBootstrap = true, onMobileData = false))
        assertFalse(AppVpnExclusionPolicy.shouldExcludeApp(isBootstrap = true, onMobileData = true))
    }

    @Test
    fun `main vpn always excludes app so workers use real network`() {
        assertTrue(AppVpnExclusionPolicy.shouldExcludeApp(isBootstrap = false, onMobileData = true))
        assertTrue(AppVpnExclusionPolicy.shouldExcludeApp(isBootstrap = false, onMobileData = false))
    }
}
