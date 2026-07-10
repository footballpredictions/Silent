package com.silent.vpn.data

import org.junit.Assert.assertEquals
import org.junit.Test

class HashChannelHelperTest {

    @Test
    fun `maxTotalWorkers scales with hash count and clamps`() {
        assertEquals(27, HashChannelHelper.maxTotalWorkers(1))
        assertEquals(54, HashChannelHelper.maxTotalWorkers(2))
        assertEquals(108, HashChannelHelper.maxTotalWorkers(4))
        // Выходы за пределы клампятся в 1..MAX_HASHES
        assertEquals(27, HashChannelHelper.maxTotalWorkers(0))
        assertEquals(108, HashChannelHelper.maxTotalWorkers(99))
    }

    @Test
    fun `normalizeTotalWorkers rounds to step of 9`() {
        assertEquals(9, HashChannelHelper.normalizeTotalWorkers(1, 4))
        assertEquals(9, HashChannelHelper.normalizeTotalWorkers(12, 4))
        assertEquals(18, HashChannelHelper.normalizeTotalWorkers(14, 4))
        assertEquals(36, HashChannelHelper.normalizeTotalWorkers(36, 4))
        assertEquals(108, HashChannelHelper.normalizeTotalWorkers(500, 4))
    }

    @Test
    fun `normalizeTotalWorkers clamps to max for hash count`() {
        // 1 хеш → максимум 27
        assertEquals(27, HashChannelHelper.normalizeTotalWorkers(108, 1))
        // 2 хеша → максимум 54
        assertEquals(54, HashChannelHelper.normalizeTotalWorkers(108, 2))
    }

    @Test
    fun `groupsForWorkers basic math`() {
        assertEquals(1, HashChannelHelper.groupsForWorkers(9))
        assertEquals(1, HashChannelHelper.groupsForWorkers(0))
        assertEquals(4, HashChannelHelper.groupsForWorkers(36))
        assertEquals(12, HashChannelHelper.groupsForWorkers(108))
        assertEquals(12, HashChannelHelper.groupsForWorkers(999))
    }

    @Test
    fun `hashesForLibclient splits trims dedupes and limits`() {
        val input = listOf(
            "hash-one,hash-two hash-three",
            "hash-one\nhash-four",
            "short",
            "  hash-five  ",
        )
        val result = HashChannelHelper.hashesForLibclient(input, totalWorkers = 36)
        // distinct, "short" длиной 5 (<6) отфильтрован, максимум MAX_HASHES=4
        assertEquals(listOf("hash-one", "hash-two", "hash-three", "hash-four"), result)
    }

    @Test
    fun `hashesForLibclient empty input`() {
        assertEquals(emptyList<String>(), HashChannelHelper.hashesForLibclient(emptyList(), 36))
    }

    @Test
    fun `workersForHashSlot distributes groups round-robin`() {
        // 36 воркеров = 4 группы, 2 хеша → по 2 группы (18) на хеш
        assertEquals(18, HashChannelHelper.workersForHashSlot(36, 0, 2))
        assertEquals(18, HashChannelHelper.workersForHashSlot(36, 1, 2))
        // 27 воркеров = 3 группы, 2 хеша → 18 и 9
        assertEquals(18, HashChannelHelper.workersForHashSlot(27, 0, 2))
        assertEquals(9, HashChannelHelper.workersForHashSlot(27, 1, 2))
        // Вне диапазона — 0
        assertEquals(0, HashChannelHelper.workersForHashSlot(36, 5, 2))
        assertEquals(0, HashChannelHelper.workersForHashSlot(36, -1, 2))
    }

    @Test
    fun `workersForHashSlot capped at MAX_WORKERS_PER_HASH`() {
        // 108 воркеров = 12 групп на 1 хеш → не больше 27
        assertEquals(27, HashChannelHelper.workersForHashSlot(108, 0, 1))
    }

    @Test
    fun `migrateLegacyPerHash maps old values to totals`() {
        assertEquals(9, HashChannelHelper.migrateLegacyPerHash(9, 4))
        assertEquals(18, HashChannelHelper.migrateLegacyPerHash(18, 4))
        assertEquals(27, HashChannelHelper.migrateLegacyPerHash(27, 4))
        assertEquals(108, HashChannelHelper.migrateLegacyPerHash(100, 4))
        // Кламп по числу хешей: 1 хеш → максимум 27
        assertEquals(27, HashChannelHelper.migrateLegacyPerHash(100, 1))
    }

    @Test
    fun `recommendedTotalWorkers matches backend formula`() {
        assertEquals(27, HashChannelHelper.recommendedTotalWorkers(1))
        assertEquals(54, HashChannelHelper.recommendedTotalWorkers(2))
        assertEquals(108, HashChannelHelper.recommendedTotalWorkers(4))
    }

    @Test
    fun `default total workers is 63`() {
        assertEquals(63, HashChannelHelper.DEFAULT_TOTAL_WORKERS)
        assertEquals(63, HashChannelHelper.normalizeTotalWorkers(HashChannelHelper.DEFAULT_TOTAL_WORKERS, 4))
        // При 2 хешах max=54 — дефолт клампится
        assertEquals(54, HashChannelHelper.normalizeTotalWorkers(HashChannelHelper.DEFAULT_TOTAL_WORKERS, 2))
    }

    @Test
    fun `signalBars thresholds`() {
        assertEquals(0, HashChannelHelper.signalBars(0, 36))
        assertEquals(1, HashChannelHelper.signalBars(1, 36))
        assertEquals(2, HashChannelHelper.signalBars(14, 36)) // ~0.39
        assertEquals(3, HashChannelHelper.signalBars(24, 36)) // ~0.67
        assertEquals(4, HashChannelHelper.signalBars(36, 36))
    }
}
