package com.silent.vpn.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.silent.vpn.test.NetworkAssumptions
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

/**
 * Реферальный flow на устройстве через MockWebServer (без реальной YuMoney-оплаты):
 * register(ref) → getReferral → payment/init → promo/check.
 */
@RunWith(AndroidJUnit4::class)
class ReferralApiInstrumentedTest {

    private lateinit var server: MockWebServer
    private lateinit var api: SilentApi

    @Before
    fun setUp() {
        NetworkAssumptions.assumeUnderlyingInternet()
        server = MockWebServer()
        server.start()
        val baseUrl = server.url("/").newBuilder().host("127.0.0.1").build().toString()
        api = Retrofit.Builder()
            .baseUrl(baseUrl)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SilentApi::class.java)
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun referralFlow_registerReferralPaymentPromo() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(201)
                .setBody("""{"message":"ok"}"""),
        )
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "referral_code": "INVITE01",
                      "referral_link": "silentvpn://ref?code=INVITE01",
                      "invited_count": 1,
                      "rewarded_count": 0,
                      "pending_count": 1,
                      "bonus_days": 30
                    }
                    """.trimIndent(),
                ),
        )
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "url": "https://yoomoney.ru/quickpay/confirm.xml?sum=199",
                      "wallet": "4100",
                      "label": "silent_test_1",
                      "amount": 199.0
                    }
                    """.trimIndent(),
                ),
        )
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "code": "PROMO5",
                      "discount_percent": 5,
                      "extra_days": 0,
                      "original_price": 199.0,
                      "discounted_price": 189.05
                    }
                    """.trimIndent(),
                ),
        )

        val reg = api.register(
            RegisterRequest("friend@example.com", "password12", "INVITE01"),
        )
        assertTrue(reg.isSuccessful)
        val regReq = server.takeRequest()
        assertEquals("/api/auth/register", regReq.path)
        assertTrue(regReq.body.readUtf8().contains("INVITE01"))

        val referral = api.getReferral()
        assertTrue(referral.isSuccessful)
        assertEquals("INVITE01", referral.body()!!.referral_code)
        assertEquals(1, referral.body()!!.pending_count)
        assertEquals("/api/users/me/referral", server.takeRequest().path)

        val pay = api.initPayment(PaymentInitRequest("monthly", null))
        assertTrue(pay.isSuccessful)
        assertEquals(199.0, pay.body()!!.amount, 0.001)
        assertEquals("/api/payments/init", server.takeRequest().path)

        val promo = api.checkPromo(PromoCheckRequest("PROMO5", "monthly"))
        assertTrue(promo.isSuccessful)
        assertEquals(5, promo.body()!!.discount_percent)
        assertEquals("/api/payments/promo/check", server.takeRequest().path)
    }
}
