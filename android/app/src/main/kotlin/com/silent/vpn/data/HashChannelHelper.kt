package com.silent.vpn.data

/** Каналы на хеш как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android): 9 / 18 / 27. */
object HashChannelHelper {
    val OPTIONS = listOf(9, 18, 27)
    const val DEFAULT_CHANNELS_PER_HASH = 9
    const val MAX_HASHES = 4

    fun normalizeChannelsPerHash(value: Int): Int = when {
        value <= 9 -> 9
        value <= 18 -> 18
        else -> 27
    }

    /** Потоков на один VK-хеш для libclient `-n` (9 / 18 / 27). libclient сам умножает на число хешей. */
    fun workersPerHashForLibclient(channelsPerHash: Int): Int =
        normalizeChannelsPerHash(channelsPerHash)

    /** Итого потоков для UI: хеши × каналы на хеш (до 108 при 4×27). */
    fun computeWorkerCount(activeHashCount: Int, channelsPerHash: Int): Int {
        val hashes = activeHashCount.coerceIn(1, MAX_HASHES)
        val per = normalizeChannelsPerHash(channelsPerHash)
        return (hashes * per).coerceIn(3, 128)
    }

    /** Сила сигнала 0–4 по доле активных каналов на хеш. */
    fun signalBars(activeChannelsOnHash: Int, channelsPerHash: Int): Int {
        val expected = normalizeChannelsPerHash(channelsPerHash)
        if (expected <= 0) return 0
        val ratio = activeChannelsOnHash.toFloat() / expected
        return when {
            ratio >= 0.85f -> 4
            ratio >= 0.6f -> 3
            ratio >= 0.35f -> 2
            activeChannelsOnHash > 0 -> 1
            else -> 0
        }
    }
}
