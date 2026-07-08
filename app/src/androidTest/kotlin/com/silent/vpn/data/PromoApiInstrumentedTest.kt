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
 * Promo check через MockWebServer **на устройстве** (localhost телефона).
 * Оплата не тестируется — только HTTP-контракт и POST body.
 */
@RunWith(AndroidJUnit4::class)
class PromoApiInstrumentedTest {

    private lateinit var server: MockWebServer
    private lateinit var api: SilentApi

    @Before
    fun setUp() {
        NetworkAssumptions.assumeUnderlyingInternet()
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
    fun promoCheck_roundTripOnDevice() = runTest {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setBody(
                    """
                    {
                      "code": "DEVICE",
                      "discount_percent": 15,
                      "extra_days": 0,
                      "original_price": 299.0,
                      "discounted_price": 254.15
                    }
                    """.trimIndent(),
                ),
        )

        val res = api.checkPromo(PromoCheckRequest("DEVICE", "monthly"))
        assertTrue(res.isSuccessful)
        assertEquals(15, res.body()!!.discount_percent)

        val recorded = server.takeRequest()
        assertEquals("/api/payments/promo/check", recorded.path)
        assertTrue(recorded.body.readUtf8().contains("DEVICE"))
    }
}
