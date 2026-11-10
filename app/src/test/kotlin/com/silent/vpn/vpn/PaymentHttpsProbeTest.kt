package com.silent.vpn.vpn

import com.silent.vpn.policy.BootstrapOverlayEndpoint
import com.silent.vpn.policy.PaymentRouteFailover
import kotlinx.coroutines.*
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.*
import org.junit.After
import org.junit.BeforeClass
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyStore
import java.util.concurrent.TimeUnit
import javax.net.ssl.*

/** Real sockets and TLS: API success cannot mask an unusable payment HTTPS path. */
class PaymentHttpsProbeTest {
    private val servers = mutableListOf<MockWebServer>()
    private val clients = mutableListOf<OkHttpClient>()

    private fun server(): MockWebServer = MockWebServer().also {
        it.useHttps(tls.socketFactory, false)
        it.start()
        servers += it
    }

    private fun client(trusted: Boolean = true, timeoutMs: Long = 3_000): OkHttpClient = OkHttpClient.Builder().apply {
        if (trusted) sslSocketFactory(tls.socketFactory, trustManager)
        followRedirects(false)
        followSslRedirects(false)
        callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
    }.build().also { clients += it }

    private fun MockWebServer.probeUrl() = url("/").newBuilder().host("localhost").build()

    @After fun close() {
        clients.forEach { it.connectionPool.evictAll(); it.dispatcher.executorService.shutdown() }
        servers.forEach { it.shutdown() }
    }

    @Test fun `successful TLS response uses HEAD without payment credentials`() = runBlocking {
        val server = server()
        server.enqueue(MockResponse().setResponseCode(200))
        assertTrue(PaymentHttpsProbe.check(client(), server.probeUrl()))
        val request = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("HEAD", request.method)
        assertNull(request.getHeader("Authorization"))
        assertNull(request.getHeader("Cookie"))
        assertEquals(0L, request.bodySize)
    }

    @Test fun `payment server failures do not count as a working route`() = runBlocking {
        val server = server()
        val client = client()
        for (code in listOf(403, 503)) {
            server.enqueue(MockResponse().setResponseCode(code))
            assertFalse(PaymentHttpsProbe.check(client, server.probeUrl()))
        }
    }

    @Test fun `TLS certificate and hostname are verified`() = runBlocking {
        val server = server()
        assertFalse(PaymentHttpsProbe.check(client(trusted = false), server.probeUrl()))
        assertFalse(PaymentHttpsProbe.check(client(), server.probeUrl().newBuilder().host("127.0.0.1").build()))
        assertEquals(0, server.requestCount)
    }

    @Test fun `redirect confirms HTTPS response without visiting payment destination`() = runBlocking {
        val server = server()
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", server.url("/invoice")))
        assertTrue(PaymentHttpsProbe.check(client(), server.probeUrl()))
        assertEquals(1, server.requestCount)
    }

    @Test fun `HTTP is refused and a stalled HTTPS route expires`() = runBlocking {
        val server = server()
        val client = client(timeoutMs = 700)
        assertFalse(PaymentHttpsProbe.check(client, server.probeUrl().newBuilder().scheme("http").build()))
        assertEquals(0, server.requestCount)
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        assertFalse(PaymentHttpsProbe.check(client, server.probeUrl()))
    }

    @Test fun `cancellation releases the outstanding network call`() = runBlocking {
        val server = server()
        val client = client()
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val job = launch(Dispatchers.IO) { PaymentHttpsProbe.check(client, server.probeUrl()) }
        assertNotNull(server.takeRequest(2, TimeUnit.SECONDS))
        job.cancelAndJoin()
        withTimeout(2_000) { while (client.dispatcher.runningCallsCount() != 0) delay(10) }
        assertTrue(job.isCancelled)
    }

    @Test fun `real HTTPS failure switches to next route`() = runBlocking {
        val failed = server().apply { enqueue(MockResponse().setResponseCode(503)) }
        val working = server().apply { enqueue(MockResponse().setResponseCode(200)) }
        val first = BootstrapOverlayEndpoint("87.58.213.193", 56000, false)
        val second = BootstrapOverlayEndpoint("78.17.74.27", 56000, false)
        var current = failed
        val stopped = mutableListOf<BootstrapOverlayEndpoint>()
        val router = PaymentRouteFailover()
        val client = client()
        assertTrue(router.prepare(listOf(first, second), { endpoint, _ ->
            current = if (endpoint == first) failed else working
            true
        }, { PaymentHttpsProbe.check(client, current.probeUrl()) }, { stopped += it }))
        assertEquals(second, router.selected)
        assertEquals(listOf(first), stopped)
        assertEquals("HEAD", failed.takeRequest().method)
        assertEquals("HEAD", working.takeRequest().method)
    }

    companion object {
        private lateinit var tls: SSLContext
        private lateinit var trustManager: X509TrustManager

        @BeforeClass @JvmStatic fun createLocalTlsFixture() {
            val directory = Files.createTempDirectory("payment-probe-tls-")
            val store = directory.resolve("localhost.p12")
            try {
                val keytool = Path.of(System.getProperty("java.home"), "bin", "keytool").toString()
                val process = ProcessBuilder(keytool, "-genkeypair", "-alias", "fixture", "-keyalg", "RSA",
                    "-keystore", store.toString(), "-storetype", "PKCS12", "-storepass", "test-password",
                    "-dname", "CN=localhost", "-ext", "SAN=dns:localhost", "-validity", "2", "-noprompt")
                    .redirectErrorStream(true).start()
                val output = process.inputStream.bufferedReader().readText()
                check(process.waitFor() == 0) { "Local TLS fixture failed: $output" }
                val password = "test-password".toCharArray()
                val keys = KeyStore.getInstance("PKCS12").apply { Files.newInputStream(store).use { load(it, password) } }
                val km = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm()).apply { init(keys, password) }
                val tm = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(keys) }
                trustManager = tm.trustManagers.filterIsInstance<X509TrustManager>().single()
                tls = SSLContext.getInstance("TLS").apply { init(km.keyManagers, tm.trustManagers, null) }
            } finally {
                Files.deleteIfExists(store)
                Files.deleteIfExists(directory)
            }
        }
    }
}
