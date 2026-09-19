package com.silent.vpn.policy

/** Публичный API без туннеля: сначала живые соты :9100, Улей :443 последним (его режут из РФ). */
object PublicApiFailoverPolicy {

    val RETIRED_HIVE_HOSTS: Set<String> = setOf(
        "132.243.234.162",
        "132-243-234-162.nip.io",
    )

    fun hostOf(raw: String): String {
        val t = raw.trim()
        if (t.isEmpty()) return ""
        val withScheme = if ("://" in t) t else "https://$t"
        return try {
            java.net.URI(withScheme).host?.lowercase().orEmpty()
        } catch (_: Exception) {
            t.substringAfter("://").substringBefore("/").substringBefore(":").lowercase()
        }
    }

    fun isRetired(raw: String?): Boolean {
        val host = hostOf(raw ?: "")
        return host.isNotEmpty() && host in RETIRED_HIVE_HOSTS
    }

    /** Prefs после смены IP Улья ещё держат 132.243 — подменяем на текущий nip.io. */
    fun rewriteStoredBase(raw: String?, currentNip: String): String {
        val nip = currentNip.trim().trimEnd('/')
        val stored = (raw ?: "").trim().trimEnd('/')
        if (stored.isBlank() || isRetired(stored)) return nip
        val host = hostOf(stored)
        val nipHost = hostOf(nip)
        if (host.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) && nip.contains(host.replace('.', '-'))) {
            return nip
        }
        if (host == nipHost) return nip
        return stored
    }

    fun orderedPublicBases(hiveHttps: List<String>, cells: List<String>): List<String> {
        val out = LinkedHashSet<String>()
        fun addAll(urls: List<String>) {
            for (raw in urls) {
                val v = raw.trim().trimEnd('/')
                if (v.isNotBlank() && !isRetired(v)) out.add(v)
            }
        }
        addAll(cells)
        addAll(hiveHttps)
        return out.toList()
    }

    /** Сеть/таймаут/5xx — пробуем следующую базу. 4xx с живого API — это ответ, не фолбэк. */
    fun shouldTryNextBase(httpCode: Int?): Boolean {
        if (httpCode == null || httpCode == 0) return true
        if (httpCode == 408 || httpCode >= 500) return true
        return false
    }

    fun connectTimeoutSec(base: String): Long =
        if (base.trim().startsWith("https://", ignoreCase = true)) 4L else 8L
}
