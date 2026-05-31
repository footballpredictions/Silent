package com.silent.vpn.data

/**
 * Сила каналов как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * `-n` = итого потоков (кратно 9). В libclient уходит только столько VK-хешей, сколько групп: n/9.
 */
object HashChannelHelper {
    const val WORKERS_PER_GROUP = 9
    const val MAX_WORKERS_PER_HASH = 27
    const val DEFAULT_TOTAL_WORKERS = 18
    const val MAX_HASHES = 4
    const val LIBCLIENT_MAX_WORKERS = 108

    fun maxTotalWorkers(activeHashCount: Int): Int =
        activeHashCount.coerceIn(1, MAX_HASHES) * MAX_WORKERS_PER_HASH

    fun normalizeTotalWorkers(value: Int, activeHashCount: Int): Int {
        val max = maxTotalWorkers(activeHashCount)
        val stepped = ((value + WORKERS_PER_GROUP / 2) / WORKERS_PER_GROUP) * WORKERS_PER_GROUP
        return stepped.coerceIn(WORKERS_PER_GROUP, max.coerceAtMost(LIBCLIENT_MAX_WORKERS))
    }

    /** Число групп libclient = n / 9. */
    fun groupsForWorkers(totalWorkers: Int): Int =
        (totalWorkers.coerceAtLeast(WORKERS_PER_GROUP) / WORKERS_PER_GROUP)
            .coerceIn(1, MAX_HASHES)

    /**
     * Передаём libclient ВСЕ доступные хеши (до MAX_HASHES).
     * libclient сам распределяет воркеров по хешам циклически — как в proxy-turn-vk-android:
     * hashList.take(3) → "-vk h1,h2,h3", "-n totalWorkers".
     */
    fun hashesForLibclient(allHashes: List<String>, totalWorkers: Int): List<String> {
        val unique = allHashes
            .flatMap { it.split(Regex("[,\\s\\n]+")) }
            .map { it.trim() }
            .filter { it.length >= 6 }
            .distinct()
        return unique.take(MAX_HASHES)
    }

    fun workersForLibclient(totalWorkers: Int, activeHashCount: Int): Int =
        normalizeTotalWorkers(totalWorkers, activeHashCount.coerceIn(1, MAX_HASHES))

    fun workersForHashSlot(totalWorkers: Int, hashIndex: Int, activeHashCount: Int): Int {
        if (hashIndex < 0 || hashIndex >= activeHashCount.coerceAtLeast(1)) return 0
        val groups = groupsForWorkers(totalWorkers)
        if (groups <= 0) return 0
        val perHash = (0 until groups).count { it % activeHashCount == hashIndex } * WORKERS_PER_GROUP
        return perHash.coerceAtMost(MAX_WORKERS_PER_HASH)
    }

    /** Старое «9/18/27 на хеш» → итого n (не умножать на число хешей). */
    fun migrateLegacyPerHash(oldPerHash: Int, activeHashCount: Int): Int {
        val asTotal = when {
            oldPerHash <= 9 -> 9
            oldPerHash <= 18 -> 18
            oldPerHash <= 27 -> 27
            oldPerHash <= 36 -> 36
            oldPerHash <= 54 -> 54
            oldPerHash <= 72 -> 72
            else -> DEFAULT_TOTAL_WORKERS
        }
        return normalizeTotalWorkers(asTotal, activeHashCount)
    }

    fun signalBars(activeWorkers: Int, totalWorkers: Int): Int {
        val expected = normalizeTotalWorkers(totalWorkers, 1).coerceAtLeast(WORKERS_PER_GROUP)
        if (expected <= 0) return 0
        val ratio = activeWorkers.toFloat() / expected
        return when {
            ratio >= 0.85f -> 4
            ratio >= 0.6f -> 3
            ratio >= 0.35f -> 2
            activeWorkers > 0 -> 1
            else -> 0
        }
    }
}
