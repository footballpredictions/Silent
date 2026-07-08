package com.silent.vpn.network

import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.policy.NetworkRecoveryPolicy
import com.silent.vpn.test.NetworkAssumptions
import org.junit.Assert.assertNotNull
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Wi‑Fi↔LTE: полный restart транспорта в CI не эмулируем.
 * На устройстве фиксируем fingerprint сети и policy transport_switch.
 * Ручной прогон: переключите Wi‑Fi↔LTE во время VPN и смотрите logcat `SilentDeviceTest`.
 */
@RunWith(AndroidJUnit4::class)
class NetworkRecoveryDeviceTest {

    @Test
    fun liveNetworkFingerprint_readable() {
        NetworkAssumptions.assumeUnderlyingInternet()
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val cm = context.getSystemService(ConnectivityManager::class.java)
        val network = cm.activeNetwork
        assertNotNull(network)
        val caps = cm.getNetworkCapabilities(network)
        assertNotNull(caps)
        val fp = when {
            caps!!.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cell"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "eth"
            else -> "unknown"
        }
        // Policy: cell→wifi и wifi→cell дают transport_switch target
        if (fp == "wifi") {
            assertNotNull(NetworkRecoveryPolicy.wifiCellTransportTarget("cell", "wifi"))
        }
        if (fp == "cell") {
            assertNotNull(NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "cell"))
        }
    }

    @Test
    fun transportSwitchReason_neverSkippedAsSpurious() {
        val skip = NetworkRecoveryPolicy.shouldSkipTransportRestart(
            NetworkRecoveryPolicy.TransportRestartInput(
                bootstrapMode = false,
                reason = "transport_switch",
                transportHealthy = true,
                workerRampUpActive = true,
                activeWorkers = 36,
                totalWorkers = 36,
                lastTransportRestartMs = 0L,
                nowMs = 100_000L,
            ),
        )
        org.junit.Assert.assertFalse(skip)
    }
}
