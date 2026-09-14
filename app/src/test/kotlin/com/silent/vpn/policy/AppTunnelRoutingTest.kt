package com.silent.vpn.policy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AppTunnelRoutingTest {

    private val self = "com.silent.vpn"
    private val vk = setOf("com.vkontakte.android", "com.vk.calls")
    private val telegram = "org.telegram.messenger"
    private val ozon = "ru.ozon.app.android"
    private val wildberries = "com.wildberries.ru"
    private val youtube = "com.google.android.youtube"
    private val installed = setOf(ozon, wildberries, youtube, telegram)

    private fun route(
        whitelist: Boolean,
        selected: Set<String>,
        includeAppInTunnel: Boolean = false,
        apps: Set<String> = installed,
    ) = AppTunnelRouting.fromIntent(
        intent = AppExclusionsPersist.TunnelIntent(whitelist = whitelist, userPackages = selected),
        selfPackage = self,
        includeAppInTunnel = includeAppInTunnel,
        vkPackages = vk,
        installedPackages = apps,
    )

    @Test
    fun `unchecked ozon and wildberries leave the tunnel in whitelist mode`() {
        val policy = route(whitelist = true, selected = setOf(youtube))
        assertTrue(policy.whitelist)
        assertTrue(ozon in policy.packages)
        assertTrue(wildberries in policy.packages)
        assertFalse(youtube in policy.packages)
        assertTrue(self in policy.packages)
    }

    @Test
    fun `empty whitelist still bypasses unchecked shops not full-tunnel`() {
        val policy = route(whitelist = true, selected = emptySet())
        assertTrue(policy.whitelist)
        assertTrue(ozon in policy.packages)
        assertTrue(wildberries in policy.packages)
        assertTrue(youtube in policy.packages)
        assertTrue(self in policy.packages)
    }

    @Test
    fun `whitelist keeps selected app in the tunnel and vk silent out of workers`() {
        val policy = route(
            whitelist = true,
            selected = setOf(telegram, "com.vkontakte.android", self),
        )
        assertTrue(policy.whitelist)
        assertFalse(telegram in policy.packages)
        assertTrue(ozon in policy.packages)
        assertTrue("com.vkontakte.android" in policy.packages)
        assertTrue(self in policy.packages)
    }

    @Test
    fun `whitelist overlay keeps silent inside so api can use the tunnel`() {
        val policy = route(
            whitelist = true,
            selected = setOf(telegram),
            includeAppInTunnel = true,
        )
        assertTrue(policy.whitelist)
        assertFalse(self in policy.packages)
        assertFalse(telegram in policy.packages)
        assertTrue(ozon in policy.packages)
        assertTrue("com.vkontakte.android" in policy.packages)
    }

    @Test
    fun `empty blacklist is silent and vk only so shops stay in the tunnel`() {
        val policy = route(whitelist = false, selected = emptySet())
        assertFalse(policy.whitelist)
        assertTrue(self in policy.packages)
        assertTrue("com.vkontakte.android" in policy.packages)
        assertFalse(ozon in policy.packages)
        assertFalse("com.android.chrome" in policy.packages)
    }

    @Test
    fun `blacklist excludes selected apps plus silent and vk not chrome`() {
        val policy = route(
            whitelist = false,
            selected = setOf(telegram, "com.android.chrome"),
        )
        assertFalse(policy.whitelist)
        assertTrue(telegram in policy.packages)
        assertTrue(self in policy.packages)
        assertTrue("com.vkontakte.android" in policy.packages)
        assertFalse("com.android.chrome" in policy.packages)
        assertFalse(ozon in policy.packages)
    }
}
