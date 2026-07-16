package com.silent.vpn.update

import org.junit.Assert.assertEquals
import org.junit.Test

class DownloadProgressTest {

    @Test
    fun resolveTotal_prefersContentLength() {
        assertEquals(1000L, DownloadProgress.resolveTotal(1000L, 999L))
    }

    @Test
    fun resolveTotal_fallsBackToExpectedSize() {
        assertEquals(5000L, DownloadProgress.resolveTotal(-1L, 5000L))
        assertEquals(5000L, DownloadProgress.resolveTotal(0L, 5000L))
    }

    @Test
    fun resolveTotal_unknownWhenBothMissing() {
        assertEquals(-1L, DownloadProgress.resolveTotal(-1L, 0L))
    }

    @Test
    fun percent_determinate() {
        assertEquals(0, DownloadProgress.percent(0, 10_000))
        assertEquals(50, DownloadProgress.percent(5_000, 10_000))
        assertEquals(100, DownloadProgress.percent(10_000, 10_000))
    }

    @Test
    fun percent_indeterminate_staysBelow100() {
        val pct = DownloadProgress.percent(10L * 1024 * 1024, -1L)
        assertEquals(true, pct in 1..95)
    }
}
