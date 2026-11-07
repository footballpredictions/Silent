package com.silent.vpn.data

import android.os.Build
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.viewModelScope
import androidx.activity.ComponentActivity
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.Gson
import com.silent.vpn.MainViewModel
import com.silent.vpn.AppScreen
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vpn.WdttTunnelManager
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.coroutines.Continuation
import kotlin.coroutines.intrinsics.suspendCoroutineUninterceptedOrReturn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Actual QR completion method + real Retrofit; no account or VPN on the emulator. */
@RunWith(AndroidJUnit4::class)
class QrAccountProfileDeviceTest {
    @Test fun publicQrLoginLoadsApprovingAccountBeforeReturningSuccess() = fixture(200, 200, true)
    @Test fun expiredSubscriptionStillLoadsApprovingAccountInsteadOfOldCache() = fixture(402, 200, false)
    @Test fun unavailableProfileKeepsTokensAndDoesNotReportCompletedLogin() = fixture(200, 503, true)
    @Test fun fullQrCompletionOpensMainWithApprovingAccount() = fixture(200, 200, true, fullFlow = true)
    @Test fun fullQrCompletionCannotOpenEmptyMainWhenProfileIsUnavailable() = fixture(200, 503, true, fullFlow = true)
    @Test fun fullQrCompletionPreservesDeviceLimitError() = fixture(403, 200, true, fullFlow = true)

    private fun fixture(registerStatus: Int, profileStatus: Int, active: Boolean, fullFlow: Boolean = false) = runBlocking {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
        assumeTrue(!SilentVpnService.isRunning && !WdttTunnelManager.running.value)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val prefs = SilentPrefs.open(context)
        val previous = prefs.all.toMap()
        val profile = """{"id":"approving-account","email":"owner@example.test","display_id":"2468","is_admin":false,"subscription":{"is_active":$active,"plan_type":"monthly","expires_at":"2099-01-01T00:00:00Z","days_left":23},"devices":[{"id":"qr-tv-device","device_name":"TV","device_type":"android","is_connected":false}],"devices_count":1,"max_devices":3}"""
        val config = """{"device_id":"qr-tv-device","wg_private_key":"fixture","wg_address":"10.66.9.2/32","wg_dns":"1.1.1.1","server_ip":"198.51.100.1","server_port":56000,"server_public_key":"fixture","wdtt_password":"fixture","vk_hashes":[],"stream_count":9}"""
        val profileAuth = CopyOnWriteArrayList<String>()
        val server = MockWebServer().apply {
            dispatcher = object : Dispatcher() {
                override fun dispatch(request: RecordedRequest): MockResponse = when (request.path?.substringBefore('?')) {
                    "/api/vpn/device/register" -> MockResponse().setResponseCode(registerStatus)
                        .setBody(when (registerStatus) {
                            200 -> config
                            402 -> """{"detail":"Subscription expired"}"""
                            else -> """{"detail":"Device limit reached"}"""
                        })
                    "/api/users/me" -> {
                        profileAuth.add(request.getHeader("Authorization").orEmpty())
                        MockResponse().setResponseCode(profileStatus).setBody(profile)
                    }
                    else -> MockResponse().setBody("{}")
                }
            }
            start()
        }
        val store = ViewModelStore()
        try {
            prefs.edit().clear().putString(SilentRepository.PREF_SERVER_URL, server.url("/").toString()).commit()
            val repo = SilentRepository(context)
            repo.startNewSession()
            val vm = withContext(Dispatchers.Main) {
                MainViewModel(repo, context).also {
                    store.put("qr", it)
                    // Exclude unrelated background polling; exercise the actual completion call.
                    it.viewModelScope.cancel()
                }
            }
            if (registerStatus == 402) {
                val old = Gson().fromJson(profile.replace("approving-account", "previous-account").replace("\"is_active\":false", "\"is_active\":true"), UserProfile::class.java)
                repo.saveCachedProfile(old)
                @Suppress("UNCHECKED_CAST")
                val state = MainViewModel::class.java.getDeclaredField("_profile").apply { isAccessible = true }
                    .get(vm) as MutableStateFlow<UserProfile?>
                state.value = old
            }
            repo.saveTokens("qr-approved-access", "qr-approved-refresh")
            val approvalApi = repo.getApi()
            // QR's public API can differ from the shared bootstrap API base.
            repo.useApiBase("http://127.0.0.1:1")
            var completionFailure: Throwable? = null
            val completed = withContext(Dispatchers.Main) {
                if (fullFlow) {
                    runCatching { finishLogin(vm) }.onFailure { completionFailure = it }.isSuccess
                } else complete(vm, approvalApi)
            }
            val expectedSuccess = registerStatus != 403 && profileStatus == 200
            assertEquals(expectedSuccess, completed)
            if (fullFlow) assertEquals(if (completed) AppScreen.MAIN else AppScreen.LOGIN, vm.screen.value)
            assertEquals(if (registerStatus == 403) emptyList<String>() else listOf("Bearer qr-approved-access"), profileAuth.toList())
            assertEquals(if (registerStatus == 403) null else "qr-approved-access", repo.getAccessToken())
            assertEquals(if (registerStatus == 403) null else "qr-approved-refresh", repo.getRefreshToken())
            if (registerStatus == 403) {
                assertNotNull(vm.authError.value)
                assertEquals(vm.authError.value, completionFailure?.cause?.message ?: completionFailure?.message)
            }
            if (expectedSuccess) {
                val actual = vm.profile.value
                assertNotNull("QR login succeeded without loading account data", actual)
                assertEquals("approving-account", actual!!.id)
                assertEquals("owner@example.test", actual.email)
                assertEquals("2468", actual.display_id)
                assertEquals(active, actual.subscription.is_active)
                assertEquals(23, actual.subscription.days_left)
                assertEquals("approving-account", repo.getCachedProfile()?.id)
            } else {
                assertNull(vm.profile.value)
            }
            assertFalse(SilentVpnService.isRunning)
            assertFalse(WdttTunnelManager.running.value)
        } finally {
            withContext(Dispatchers.Main) { store.clear() }
            server.shutdown()
            prefs.edit().clear().apply {
                previous.forEach { (key, value) -> when (value) {
                    is String -> putString(key, value)
                    is Boolean -> putBoolean(key, value)
                    is Int -> putInt(key, value)
                    is Long -> putLong(key, value)
                    is Float -> putFloat(key, value)
                    is Set<*> -> putStringSet(key, value.filterIsInstance<String>().toSet())
                } }
            }.commit()
        }
    }

    private suspend fun complete(vm: MainViewModel, api: SilentApi): Boolean =
        suspendCoroutineUninterceptedOrReturn { continuation ->
            MainViewModel::class.java.getDeclaredMethod("applyLoginAfterQrTokens", SilentApi::class.java,
                Boolean::class.javaPrimitiveType, Continuation::class.java).apply { isAccessible = true }
                .invoke(vm, api, false, continuation)
        }

    private suspend fun finishLogin(vm: MainViewModel): Unit =
        suspendCoroutineUninterceptedOrReturn { continuation ->
            MainViewModel::class.java.getDeclaredMethod("completeLoginFromTokens", String::class.java,
                String::class.java, ComponentActivity::class.java, Continuation::class.java)
                .apply { isAccessible = true }
                .invoke(vm, "qr-approved-access", "qr-approved-refresh", null, continuation)
        }
}
