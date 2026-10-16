package com.silent.vpn.data

import android.content.Context
import android.os.SystemClock
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import com.silent.vpn.vpn.BrowserScopedTunnel
import org.json.JSONObject

/** Independent override: never rewrites either saved app/site list or its mode. */
object RussianServices {
    const val ENABLED_KEY = "ru_direct"
    private const val CACHE_KEY = "russian_routing_policy_v1"
    private val fetching = AtomicBoolean(false)
    @Volatile private var attemptedAt = 0L
    @Volatile private var bundled: String? = null
    enum class Delivery { WAITING, LOADING, RECEIVED, FAILED }
    private val mutableDelivery = MutableStateFlow(Delivery.WAITING)
    val delivery = mutableDelivery.asStateFlow()
    private val generation = AtomicLong()
    private val mutableChanges = MutableStateFlow(0L)
    val changes = mutableChanges.asStateFlow()
    @Volatile private var receivedRevision: String? = null

    fun enabled(context: Context): Boolean = SilentPrefs.open(context).getBoolean(ENABLED_KEY, false)

    @Synchronized fun setEnabled(context: Context, enabled: Boolean) {
        check(SilentPrefs.open(context).edit().putBoolean(ENABLED_KEY, enabled).commit()) {
            "Не удалось сохранить режим российских сервисов"
        }
        val version = generation.incrementAndGet()
        attemptedAt = 0L
        receivedRevision = null
        mutableDelivery.value = Delivery.WAITING
        mutableChanges.value = version
    }

    /** Called only after native POLICY_READY (or READY for the initial config). */
    @Synchronized fun applied(context: Context, policy: JSONObject) {
        if (enabled(context) && policy.optBoolean("enabled") &&
            policy.optString("revision") == receivedRevision) mutableDelivery.value = Delivery.RECEIVED
    }

    fun tunnelStopped() {
        if (mutableDelivery.value == Delivery.RECEIVED) mutableDelivery.value = Delivery.WAITING
    }

    private fun valid(raw: String): JSONObject? = runCatching {
        require(raw.toByteArray().size <= 262_144)
        val policy = JSONObject(raw)
        require(policy.getInt("schema_version") == 1)
        require(policy.getString("revision").matches(Regex("[0-9a-f]{64}")))
        for (key in listOf("direct_domains", "vpn_domains")) {
            val domains = policy.getJSONArray(key)
            require(domains.length() <= 2000)
            for (index in 0 until domains.length()) {
                val domain = domains.get(index) as String
                require(domain.length in 1..253 && domain == domain.lowercase())
                require(domain.split('.').all { it.length in 1..63 && it.matches(Regex("[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")) })
            }
        }
        policy
    }.getOrNull()

    fun config(context: Context): JSONObject {
        val cached = SilentPrefs.open(context).getString(CACHE_KEY, null)?.let(::valid)
        val fallback = bundled ?: context.assets.open("russian-services-policy.json").bufferedReader().use { it.readText() }
            .also { bundled = it }
        return (cached ?: checkNotNull(valid(fallback)) { "Некорректная политика российских сервисов" })
            .put("enabled", enabled(context))
    }

    /** Native relay shares the live WG device: no overlay or second VPN session. */
    fun refresh(context: Context): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (!enabled(context) || (attemptedAt > 0 && now - attemptedAt < 10_000) || !fetching.compareAndSet(false, true)) return false
        attemptedAt = now
        val requestGeneration = generation.get()
        receivedRevision = null
        mutableDelivery.value = Delivery.LOADING
        try {
            val previous = config(context).getString("revision")
            val policy = downloadPolicy() ?: return false
            return synchronized(this) {
                if (!enabled(context) || requestGeneration != generation.get()) return@synchronized false
                check(SilentPrefs.open(context).edit().putString(CACHE_KEY, policy.toString()).commit())
                receivedRevision = policy.getString("revision")
                receivedRevision != previous
            }
        } catch (_: Exception) {
            return false
        } finally {
            synchronized(this) {
                if (requestGeneration == generation.get() && receivedRevision == null) mutableDelivery.value = Delivery.FAILED
            }
            fetching.set(false)
        }
    }

    private fun downloadPolicy(): JSONObject? {
        val connection = URL("${BrowserScopedTunnel.OTA_BASE_URL}/api/vpn/routing-policy")
            .openConnection(Proxy.NO_PROXY) as HttpURLConnection
        return try {
            connection.connectTimeout = 1_000
            connection.readTimeout = 5_000
            connection.useCaches = false
            connection.instanceFollowRedirects = false
            if (connection.responseCode != 200 || connection.getHeaderField("X-Silent-Upstream") != "1") return null
            val deadline = SystemClock.elapsedRealtime() + 5_000
            val bytes = connection.inputStream.use { input ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (output.size() <= 262_144) {
                    check(SystemClock.elapsedRealtime() < deadline)
                    val n = input.read(buffer, 0, minOf(buffer.size, 262_145 - output.size()))
                    if (n < 0) break
                    output.write(buffer, 0, n)
                }
                output.toByteArray()
            }
            valid(bytes.toString(Charsets.UTF_8))
        } finally { connection.disconnect() }
    }

    fun hasReceivedPolicy(): Boolean = receivedRevision != null

    fun applicationFailed() { mutableDelivery.value = Delivery.FAILED }
}
