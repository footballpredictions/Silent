package com.silent.vpn.update

import com.silent.vpn.data.SilentApi
import com.silent.vpn.data.UpdateCheckResponse
import com.silent.vpn.policy.UpdateUrlResolver
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okio.Buffer
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.io.IOException

class OtaUpdateFlowTest {
    @get:Rule val temp = TemporaryFolder()
    private val publicJson = """{"android":{"version":"1.0.999","filename":"new.apk","size":123,"download_url":"https://github.com/releases/new.apk"}}"""

    @Test fun `blocked pages then vpn discovers and downloads apk on wifi and lte`() = runBlocking {
        for (mobile in listOf(false, true)) {
            MockWebServer().use { tunnel ->
                tunnel.start()
                val bytes = ByteArray(5 * 1024 * 1024 + 17) { (it % 251).toByte() }
                tunnel.enqueue(MockResponse().setBody("""{"available":true,"version":"1.0.999","filename":"new.apk","size":${bytes.size},"github_download_url":"https://blocked.invalid/new.apk","tunnel_download_url":"/api/updates/download/android"}"""))
                // Local proxy strips Content-Length: actual downloader must still stream beyond 4MB.
                tunnel.enqueue(MockResponse().setChunkedBody(Buffer().write(bytes), 64 * 1024))
                val api = Retrofit.Builder().baseUrl(tunnel.url("/"))
                    .addConverterFactory(GsonConverterFactory.create()).build().create(SilentApi::class.java)
                val gate = OtaCheckGate()
                assertTrue(gate.tryStart(1_000, false))
                val before = OtaUpdateDiscovery.check(mobile, false, "android", "1.0.1",
                    publicJson = { throw IOException("carrier whitelist") },
                    tunnelCheck = { fail("No tunnel before VPN"); null })
                assertNull(before)
                // VPN ready arrived while the public check was still in flight.
                assertFalse(gate.tryStart(1_100, true))
                assertTrue(gate.finish(1_200))
                assertTrue(gate.tryStart(1_201, true))
                val offer = OtaUpdateDiscovery.check(mobile, true, "android", "1.0.1",
                    publicJson = { fail("Excluded public request must not run"); null },
                    tunnelCheck = { withContext(Dispatchers.IO) { api.checkUpdate("android", "1.0.1").body() } })!!
                assertTrue(offer.available)
                assertEquals("/api/updates/check?platform=android&version=1.0.1", tunnel.takeRequest().path)
                val url = UpdateUrlResolver.resolveUpdateDownloadUrl(UpdateUrlResolver.OtaUrlInput(
                    onMobileData = mobile, appExcludedFromVpn = true, mainVpnTunnelUp = true,
                    isBootstrapMode = false, publicServerUrl = "https://blocked.invalid",
                    preferredHttpsBase = tunnel.url("/").toString(), tunnelProxyActive = true,
                    githubDownloadUrl = offer.github_download_url, tunnelDownloadPath = offer.tunnel_download_url,
                ))!!
                val progress = mutableListOf<Int>()
                val file = AppUpdateManager.downloadApkToDirectory(temp.newFolder(), url, offer.filename!!,
                    OkHttpClient(), offer.size) { progress.add(it) }
                assertArrayEquals(bytes, file.readBytes())
                assertEquals("/api/updates/download/android", tunnel.takeRequest().path)
                assertEquals(100, progress.last())
                assertEquals(2, tunnel.requestCount)
                assertFalse(gate.finish(1_300))
            }
        }
    }

    @Test fun `wifi without vpn keeps pages independent of public hive ip`() = runTest {
        val offer = OtaUpdateDiscovery.check(false, false, "android", "1.0.1", { publicJson },
            { fail("No tunnel"); null })!!
        assertTrue(offer.available)
        assertEquals("https://github.com/releases/new.apk", offer.github_download_url)
    }

    @Test fun `wifi tunnel failure falls back to pages`() = runTest {
        val offer = OtaUpdateDiscovery.check(false, true, "android", "1.0.1", { publicJson },
            { throw IOException("tunnel unavailable") })!!
        assertTrue(offer.available)
    }

    @Test fun `lte vpn never stalls on blocked public fallback`() = runTest {
        assertNull(OtaUpdateDiscovery.check(true, true, "android", "1.0.1",
            { fail("Blocked public fallback"); null }, { throw IOException("tunnel unavailable") }))
    }

    @Test fun `up to date tunnel result clears offer without public request`() = runTest {
        val offer = OtaUpdateDiscovery.check(true, true, "android", "1.0.999",
            { fail("Public request"); null }, { UpdateCheckResponse(available = false) })!!
        assertFalse(offer.available)
    }

    @Test fun `wifi tunnel timeout leaves budget for pages`() = runTest {
        assertTrue(OtaUpdateDiscovery.check(false, true, "android", "1.0.1", { publicJson },
            { delay(60_000); null })!!.available)
    }

    @Test fun `cancellation is not converted to unavailable update`() = runTest {
        try {
            OtaUpdateDiscovery.check(false, true, "android", "1.0.1", { publicJson },
                { throw CancellationException("VPN session cancelled") })
            fail("Cancellation must propagate")
        } catch (_: CancellationException) { }
    }

    @Test fun `cooldown blocks repeated screen checks but never tunnel ready`() {
        val gate = OtaCheckGate()
        assertTrue(gate.tryStart(1_000, false))
        assertFalse(gate.tryStart(1_010, false))
        assertFalse(gate.finish(1_020))
        assertFalse(gate.tryStart(1_030, false))
        assertTrue(gate.tryStart(1_040, true))
        assertFalse(gate.finish(1_050))
        assertTrue(gate.tryStart(31_051, false))
    }
}
