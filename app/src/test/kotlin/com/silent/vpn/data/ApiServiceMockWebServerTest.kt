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
    fun `profile delivers quarterly warning without a second api request and rejects stale estimates`() = runTest {
        server.enqueue(MockResponse().setBody("""{"id":"local","email":"local@example.org","display_id":"local","subscription":{"is_active":true,"plan_type":"quarterly","expires_at":"2026-12-28T00:00:00Z","days_left":91},"devices":[],"devices_count":0,"max_devices":3,"payment_previews":{"quarterly_5":{"amount":792,"expires_at":"2027-02-20T22:07:16Z","calculated_at":"2026-09-28T00:00:00.123456Z","message":"3 месяца на 5 устройств: 91.0 дн. покупки + 54.9 дн. остатка"}}}"""))
        val profile = api.getProfile().body()!!
        val preview = profile.payment_previews!!["quarterly_5"]!!
        assertTrue(preview.message.contains("91.0 дн. покупки + 54.9"))
        assertTrue(preview.isFresh(1790553660000L))
        org.junit.Assert.assertFalse(preview.isFresh(1790553901000L))
        assertEquals(1, server.requestCount)
    }

    @Test
    fun `prepaid checkout reads server warning and keeps pending despite active subscription`() = runTest {
        server.enqueue(MockResponse().setBody("""{"amount":330,"expires_at":"2026-10-25T01:05:27Z","message":"Остаток 15 дн. пересчитается в 9 дн. Подписка до 25.10.2026."}"""))
        val preview = api.previewPayment(PaymentInitRequest("monthly_5")).body()!!
        assertEquals(330.0, preview.amount, 0.001)
        assertTrue(preview.message.contains("9 дн."))
        assertEquals("/api/payments/preview", server.takeRequest().path)
        server.enqueue(MockResponse().setBody("""{"label":"silent_test","status":"pending","plan_type":"monthly_5","amount":330,"subscription_applied":false}"""))
        val pending = api.getPaymentStatus("silent_test").body()!!
        assertEquals("pending", pending.status)
        assertEquals(false, pending.subscription_applied)
        server.enqueue(MockResponse().setBody("""{"label":"silent_test","status":"completed","plan_type":"monthly_5","amount":330,"subscription_applied":true}"""))
        assertEquals(true, api.getPaymentStatus("silent_test").body()!!.subscription_applied)
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
                      "version": "1.0.152",
                      "filename": "app.apk",
                      "size": 27117932,
                      "download_url": "/api/updates/download/android",
                      "github_download_url": "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.152/app.apk",
                      "tunnel_download_url": "/api/updates/download/android"
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.checkUpdate(platform = "android", version = "1.0.151")
        assertTrue(res.isSuccessful)
        val body = res.body()!!
        assertTrue(body.available)
        assertEquals("1.0.152", body.version)
        assertTrue(body.github_download_url!!.contains("github.com"))
        assertEquals("/api/updates/download/android", body.tunnel_download_url)
    }

    @Test
    fun `register sends referral_or_promo when provided`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(201)
                .setBody("""{"message":"Регистрация успешна. Проверьте email для подтверждения."}"""),
        )

        val res = api.register(
            RegisterRequest(
                email = "invitee@example.com",
                password = "password12",
                referral_or_promo = "ABCD1234",
            ),
        )
        assertTrue(res.isSuccessful)

        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/auth/register", recorded.path)
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"email\":\"invitee@example.com\""))
        assertTrue(body.contains("\"referral_or_promo\":\"ABCD1234\""))
    }

    @Test
    fun `register omits blank referral_or_promo`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(201)
                .setBody("""{"message":"ok"}"""),
        )

        val res = api.register(RegisterRequest("a@b.co", "password12", null))
        assertTrue(res.isSuccessful)
        val body = server.takeRequest().body.readUtf8()
        assertTrue(body.contains("\"email\":\"a@b.co\""))
        // Gson may omit nulls; ensure we did not force an empty code
        assertTrue(!body.contains("\"referral_or_promo\":\"\""))
    }

    @Test
    fun registerSkipConfirmFlagStaysStringForMapParser() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(201)
                .setBody(
                    """{"message":"Регистрация успешна. Можно войти.","email_confirmation_required":"false"}""",
                ),
        )
        val res = api.register(RegisterRequest("a@b.co", "password12", null))
        assertTrue(res.isSuccessful)
        assertEquals("false", res.body()!!["email_confirmation_required"])
    }

    @Test
    fun `getReferral parses code link and stats`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "referral_code": "ABCD1234",
                      "referral_link": "silentvpn://ref?code=ABCD1234",
                      "invited_count": 2,
                      "rewarded_count": 1,
                      "pending_count": 1,
                      "bonus_days": 30
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.getReferral()
        assertTrue(res.isSuccessful)
        val info = res.body()!!
        assertEquals("ABCD1234", info.referral_code)
        assertEquals("silentvpn://ref?code=ABCD1234", info.referral_link)
        assertEquals(2, info.invited_count)
        assertEquals(1, info.rewarded_count)
        assertEquals(1, info.pending_count)
        assertEquals(30, info.bonus_days)

        val recorded = server.takeRequest()
        assertEquals("GET", recorded.method)
        assertEquals("/api/users/me/referral", recorded.path)
    }

    @Test
    fun `theme includes bonuses and register referral fields`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "primary_color": "#000000",
                      "background_color": "#FFFFFF",
                      "text_color": "#000000",
                      "accent_color": "#1A1A1A",
                      "menu_bonuses_label": "Бонусы",
                      "bonuses_title": "Бонусы",
                      "bonuses_intro_text": "Реф и промо в одном тексте",
                      "bonuses_referral_title": "Ваша ссылка",
                      "bonuses_rules_text": "",
                      "register_referral_or_promo_label": "Промокод или реферальный код"
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.getTheme()
        assertTrue(res.isSuccessful)
        val theme = res.body()!!
        assertEquals("Бонусы", theme.menu_bonuses_label)
        assertEquals("Ваша ссылка", theme.bonuses_referral_title)
        assertEquals("Реф и промо в одном тексте", theme.bonuses_intro_text)
        assertEquals("", theme.bonuses_rules_text)
        assertEquals("Промокод или реферальный код", theme.register_referral_or_promo_label)
    }

    @Test
    fun `payment init may include promo_code from registration`() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "url": "https://yoomoney.ru/quickpay/confirm.xml?sum=199",
                      "wallet": "4100",
                      "label": "silent_u_abc",
                      "amount": 199.0
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.initPayment(PaymentInitRequest(plan_type = "monthly", promo_code = "SAVE10"))
        assertTrue(res.isSuccessful)
        assertEquals(199.0, res.body()!!.amount, 0.001)

        val recorded = server.takeRequest()
        assertEquals("/api/payments/init", recorded.path)
        val body = recorded.body.readUtf8()
        assertTrue(body.contains("\"plan_type\":\"monthly\""))
        assertTrue(body.contains("\"promo_code\":\"SAVE10\""))
    }

    @Test
    fun `qr poll pending then approved returns tokens`() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"pending"}"""))
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "status": "approved",
                      "access_token": "access-tv",
                      "refresh_token": "refresh-tv"
                    }
                    """.trimIndent(),
                ),
        )

        val pending = api.qrPoll("Abc_123-token")
        assertTrue(pending.isSuccessful)
        assertEquals("pending", pending.body()!!.status)

        val approved = api.qrPoll("Abc_123-token")
        assertTrue(approved.isSuccessful)
        assertEquals("approved", approved.body()!!.status)
        assertEquals("access-tv", approved.body()!!.access_token)
        assertEquals("refresh-tv", approved.body()!!.refresh_token)

        val first = server.takeRequest()
        assertEquals("GET", first.method)
        assertEquals("/api/auth/qr/poll?token=Abc_123-token", first.path)
        server.takeRequest()
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
