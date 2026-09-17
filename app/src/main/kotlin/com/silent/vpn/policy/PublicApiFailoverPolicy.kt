package com.silent.vpn.policy

/** Публичный API без туннеля: сначала живые соты :9100, Улей :443 последним (его режут из РФ). */
object PublicApiFailoverPolicy {

    fun orderedPublicBases(hiveHttps: List<String>, cells: List<String>): List<String> {
        val out = LinkedHashSet<String>()
        fun addAll(urls: List<String>) {
            for (raw in urls) {
                val v = raw.trim().trimEnd('/')
                if (v.isNotBlank()) out.add(v)
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
