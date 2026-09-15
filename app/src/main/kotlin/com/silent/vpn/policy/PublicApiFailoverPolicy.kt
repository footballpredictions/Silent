package com.silent.vpn.policy

/** Публичный API без туннеля: сначала Улей, соты по очереди если Улей не ответил. */
object PublicApiFailoverPolicy {

    fun orderedPublicBases(hiveHttps: List<String>, cells: List<String>): List<String> {
        val out = LinkedHashSet<String>()
        fun addAll(urls: List<String>) {
            for (raw in urls) {
                val v = raw.trim().trimEnd('/')
                if (v.isNotBlank()) out.add(v)
            }
        }
        addAll(hiveHttps)
        addAll(cells)
        return out.toList()
    }
}
