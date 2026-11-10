package com.silent.vpn.vpn

import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import kotlin.coroutines.resume

/** A read-only, authenticated TLS connection. No payment creation, cookies or API tokens. */
internal object PaymentHttpsProbe {
    val site: HttpUrl = "https://yoomoney.ru/".toHttpUrl()

    suspend fun check(client: OkHttpClient, url: HttpUrl = site): Boolean {
        if (!url.isHttps) return false
        val request = Request.Builder().url(url).head().header("Cache-Control", "no-cache").build()
        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (continuation.isActive) continuation.resume(false)
                }

                override fun onResponse(call: Call, response: Response) {
                    val available = response.use { it.handshake != null && it.code in 200..399 }
                    if (continuation.isActive) continuation.resume(available)
                }
            })
        }
    }
}
