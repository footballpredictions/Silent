package com.silent.vpn.vk

object HashParser {
    private val joinRegex = Regex("""/join/([A-Za-z0-9_\-]+)""", RegexOption.IGNORE_CASE)

    fun extract(raw: String): String? {
        var s = raw.trim()
        if (s.isEmpty()) return null
        s = s.substringBefore('?').substringBefore('#').trim().trimEnd('/')
        joinRegex.find(s)?.groupValues?.getOrNull(1)?.let { return it.trimEnd('/') }
        Regex("""join/([A-Za-z0-9_\-]+)""", RegexOption.IGNORE_CASE).find(s)?.groupValues?.getOrNull(1)?.let {
            return it.trimEnd('/')
        }
        val bare = s.removePrefix("https://").removePrefix("http://")
            .removePrefix("www.").trim()
        if (bare.length in 6..128 && bare.all { it.isLetterOrDigit() || it == '-' || it == '_' }) {
            return bare
        }
        return null
    }

    /** Чистый хеш для libclient — из ссылки vk.com/call/join/… или bare token (reference 1.1.8+). */
    fun normalizeList(raw: List<String>): List<String> =
        raw.mapNotNull { extract(it) }.distinct()
}
