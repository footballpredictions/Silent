package com.silent.vpn.data

import com.silent.vpn.policy.ApiRoutePolicy
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * JVM MockWebServer: контракт JSON для promo / sync-state / OTA без staging API.
 * Маршрут promo на LTE — [ApiRoutePolicy.userApiRoute] (overlay), не initPayment.
 */
class ApiServiceMockWebServerTest {

    private lateinit var server: MockWebServer
    private lateinit var api: SilentApi

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
        api = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SilentApi::class.java)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun `promo check parses valid response`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "code": "TEST10",
                      "discount_percent": 10,
                      "extra_days": 0,
                      "original_price": 299.0,
                      "discounted_price": 269.1
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.checkPromo(PromoCheckRequest("TEST10", "monthly"))
        assertTrue(res.isSuccessful)
        val body = res.body()!!
        assertEquals("TEST10", body.code)
        assertEquals(10, body.discount_percent)
        assertEquals(269.1, body.discounted_price, 0.001)

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/payments/promo/check", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("\"code\":\"TEST10\""))
    }

    @Test
    fun `sync-state parses revisions and changed list`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "revision": 42,
                      "hashes": 10,
                      "theme": 5,
                      "profile": 7,
                      "changed": ["profile", "theme"]
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.getSyncState(hashesSince = 9, themeSince = 4, profileSince = 6)
        assertTrue(res.isSuccessful)
        val body = res.body()!!
        assertEquals(42L, body.revision)
        assertEquals(listOf("profile", "theme"), body.changed)

        val recorded = server.takeRequest()
        assertEquals("/api/vpn/sync-state?hashes_since=9&theme_since=4&profile_since=6", recorded.path)
    }

    @Test
    fun `update check parses github and tunnel urls`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "available": true,
                      "version": "1.0.151",
                      "filename": "app.apk",
                      "size": 27117932,
                      "download_url": "/api/updates/download/android",
                      "github_download_url": "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.151/app.apk",
                      "tunnel_download_url": "/api/updates/download/android"
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.checkUpdate(platform = "android", version = "1.0.150")
        assertTrue(res.isSuccessful)
        val body = res.body()!!
        assertTrue(body.available)
        assertEquals("1.0.151", body.version)
        assertTrue(body.github_download_url!!.contains("github.com"))
        assertEquals("/api/updates/download/android", body.tunnel_download_url)
    }

    @Test
    fun `promo route policy uses overlay on lte excluded vpn`() {
        val route = ApiRoutePolicy.userApiRoute(
            ApiRoutePolicy.RouteContext(
                onMobileData = true,
                appExcludedFromVpn = true,
                mainVpnTunnelUp = true,
                tunnelDataSyncCompleted = true,
                apiOverlayActive = false,
                bootstrapMode = false,
                tunnelReady = true,
            ),
        )
        assertEquals(ApiRoutePolicy.UserApiRoute.OVERLAY_BRIEF, route)
    }
}
