package com.silent.vpn.network

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.test.DeviceNetworkReporter
import com.silent.vpn.vpn.VpnNetworkHelper
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Всегда выполняется на телефоне/эмуляторе — проверяет, что тестовый APK установился
 * и [VpnNetworkHelper] читает реальный [ConnectivityManager].
 */
@RunWith(AndroidJUnit4::class)
class DeviceNetworkSmokeTest {

    @Test
    fun deviceContextAndNetworkProbe() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertNotNull(context.packageName)
        // Не assert на wifi/lte — только что вызов не падает
        VpnNetworkHelper.isOnMobileData(context)
        VpnNetworkHelper.hasAnyUnderlyingInternet(context)
        DeviceNetworkReporter.logState(context)
    }
}
