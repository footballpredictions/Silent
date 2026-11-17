package com.silent.vpn.vpn

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl
import okhttp3.OkHttpClient

/** Conscrypt writes close_notify when an idle TLS socket is evicted, even after HEAD finished. */
internal object PaymentProbeClient {
    suspend fun check(client: OkHttpClient, url: HttpUrl = PaymentHttpsProbe.site): Boolean = withContext(Dispatchers.IO) {
        try { PaymentHttpsProbe.check(client, url) } finally {
            client.connectionPool.evictAll()
            client.dispatcher.executorService.shutdown()
        }
    }
}
