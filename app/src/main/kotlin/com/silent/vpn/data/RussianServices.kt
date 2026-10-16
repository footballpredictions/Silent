package com.silent.vpn.data

import android.content.Context
import android.os.SystemClock
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean
import org.json.JSONObject

/** Independent override: never rewrites either saved app/site list or its mode. */
object RussianServices {
    const val ENABLED_KEY = "ru_direct"
    private const val CACHE_KEY = "russian_routing_policy_v1"
    private val fetching = AtomicBoolean(false)
    @Volatile private var attemptedAt = 0L
    @Volatile private var bundled: String? = null

    fun enabled(context: Context): Boolean = SilentPrefs.open(context).getBoolean(ENABLED_KEY, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        check(SilentPrefs.open(context).edit().putBoolean(ENABLED_KEY, enabled).commit()) {
            "Не удалось сохранить режим российских сервисов"
        }
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

    /** Bounded public read; malformed/error replies never replace a usable policy. */
    fun refresh(context: Context): Boolean {
        val now = SystemClock.elapsedRealtime()
        if (!enabled(context) || (attemptedAt > 0 && now - attemptedAt < 60_000) || !fetching.compareAndSet(false, true)) return false
        attemptedAt = now
        try {
            val previous = config(context).getString("revision")
            for (base in listOf(SilentRepository.DEFAULT_SERVER_URL,
                "http://87.58.213.193:9100", "http://78.17.74.27:9100",
                "http://192.177.26.38:9100", "http://89.37.192.241:9100")) {
                val connection = URL("$base/api/vpn/routing-policy").openConnection(Proxy.NO_PROXY) as HttpURLConnection
                try {
                    connection.connectTimeout = 2_000
                    connection.readTimeout = 2_000
                    connection.instanceFollowRedirects = false
                    if (connection.responseCode != 200) continue
                    val bytes = connection.inputStream.use { input ->
                        val output = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        while (output.size() <= 262_144) {
                            val n = input.read(buffer, 0, minOf(buffer.size, 262_145 - output.size()))
                            if (n < 0) break
                            output.write(buffer, 0, n)
                        }
                        output.toByteArray()
                    }
                    val policy = valid(bytes.toString(Charsets.UTF_8)) ?: continue
                    if (policy.getString("revision") == previous) return false
                    check(SilentPrefs.open(context).edit().putString(CACHE_KEY, policy.toString()).commit())
                    return true
                } catch (_: Exception) { } finally { connection.disconnect() }
            }
        } finally { fetching.set(false) }
        return false
    }
}
