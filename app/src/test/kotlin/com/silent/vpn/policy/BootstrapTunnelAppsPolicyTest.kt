package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BootstrapTunnelAppsPolicyTest {

    private val self = "com.silent.vpn"
    private val vk = setOf("com.vkontakte.android", "com.vk.calls")

    @Test
    fun anyMailClientStaysInTunnelIncludingStockOem() {
        val mail = listOf(
            "com.google.android.gm",
            "ru.mail.mailapp",
            "com.android.email",
            "com.vivo.email",
            "com.huawei.email",
            "com.samsung.android.email.provider",
            "ru.yandex.mail",
            "com.microsoft.office.outlook",
            "com.fsck.k9",
        )
        val installed = mail.toSet() + vk + self + setOf("com.android.chrome")
        val excluded = BootstrapTunnelAppsPolicy.excludeFromTunnel(
            vkPackages = vk,
            installedPackages = installed,
            selfPackage = self,
        )
        assertEquals(vk, excluded)
        for (pkg in mail) {
            assertFalse(pkg, pkg in excluded)
        }
        assertFalse(self in excluded)
        assertFalse("com.android.chrome" in excluded)
    }

    @Test
    fun missingVkPackagesAreNotExcluded() {
        val excluded = BootstrapTunnelAppsPolicy.excludeFromTunnel(
            vkPackages = vk,
            installedPackages = setOf(self, "com.android.email"),
            selfPackage = self,
        )
        assertTrue(excluded.isEmpty())
        assertFalse("com.android.email" in excluded)
    }
}
