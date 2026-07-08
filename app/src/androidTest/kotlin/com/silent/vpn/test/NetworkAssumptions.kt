package com.silent.vpn.test

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import org.junit.Assume

/**
 * Условные ветки LTE/Wi‑Fi: если сеть не подходит — тест **пропускается**, а не падает.
 * Прогоните suite дважды (на Wi‑Fi и на LTE) или используйте [DeviceNetworkReporter].
 */
object NetworkAssumptions {
    fun targetContext(): Context = InstrumentationRegistry.getInstrumentation().targetContext

    fun assumeWifi(context: Context = targetContext()) {
        Assume.assumeTrue(
            "Нужен Wi‑Fi: подключитесь к Wi‑Fi (мобильные данные могут остаться как fallback)",
            !VpnNetworkHelper.isOnMobileData(context),
        )
    }

    fun assumeMobileData(context: Context = targetContext()) {
        Assume.assumeTrue(
            "Нужен LTE: выключите Wi‑Fi, оставьте мобильный интернет",
            VpnNetworkHelper.isOnMobileData(context),
        )
    }

    fun assumeSilentVpnUp() {
        Assume.assumeTrue(
            "Нужен включённый VPN Silent (тумблер в приложении)",
            SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value,
        )
    }

    fun assumeUnderlyingInternet(context: Context = targetContext()) {
        Assume.assumeTrue(
            "Нужен интернет на устройстве",
            VpnNetworkHelper.hasAnyUnderlyingInternet(context),
        )
    }
}
