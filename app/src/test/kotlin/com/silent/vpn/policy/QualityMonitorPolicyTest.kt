package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QualityMonitorPolicyTest {

    @Test
    fun `mbps from byte delta`() {
        // 7_500_000 bytes in 10s = 6 Mbps
        val m = QualityMonitorPolicy.mbps(7_500_000, 10_000)
        assertEquals(6.0, m, 0.01)
    }

    @Test
    fun `idle when almost no traffic`() {
        val r = QualityMonitorPolicy.evaluate(
            QualityMonitorPolicy.SampleInput(
                elapsedMs = 60_000,
                rxDelta = 1000,
                txDelta = 500,
            ),
        )
        assertEquals(QualityMonitorPolicy.Verdict.IDLE, r.verdict)
        assertFalse(QualityMonitorPolicy.isProblem(r.verdict))
    }

    @Test
    fun `slow when night-like rates with real traffic`() {
        // ~3 Mbps down, ~0.3 Mbps up over 60s — как жалоба 10→11.09
        val rx = (3.0 * 1_000_000 / 8.0 * 60).toLong()
        val tx = (0.3 * 1_000_000 / 8.0 * 60).toLong()
        val r = QualityMonitorPolicy.evaluate(
            QualityMonitorPolicy.SampleInput(
                elapsedMs = 60_000,
                rxDelta = rx,
                txDelta = tx,
            ),
        )
        assertEquals(QualityMonitorPolicy.Verdict.SLOW, r.verdict)
        assertTrue(QualityMonitorPolicy.isProblem(r.verdict))
        assertTrue(r.likelyCause.contains("mobile_or_wrap"))
    }

    @Test
    fun `ok when rates healthy`() {
        val rx = (20.0 * 1_000_000 / 8.0 * 60).toLong()
        val tx = (5.0 * 1_000_000 / 8.0 * 60).toLong()
        val r = QualityMonitorPolicy.evaluate(
            QualityMonitorPolicy.SampleInput(
                elapsedMs = 60_000,
                rxDelta = rx,
                txDelta = tx,
            ),
        )
        assertEquals(QualityMonitorPolicy.Verdict.OK, r.verdict)
    }

    @Test
    fun `tunnel api hard fail only when tunnel looks dead`() {
        val r = QualityMonitorPolicy.evaluate(
            QualityMonitorPolicy.SampleInput(
                elapsedMs = 60_000,
                rxDelta = 100,
                txDelta = 50,
                handshakeAgeSec = 500,
                tunnelApiOk = false,
            ),
        )
        assertEquals(QualityMonitorPolicy.Verdict.TUNNEL_API_FAIL, r.verdict)
    }

    @Test
    fun `tunnel api soft when handshake fresh and traffic like youtube`() {
        // Как ручной замер: ~3.4 Mbps / 4с, HS 28с, API probe fail
        val r = QualityMonitorPolicy.evaluate(
            QualityMonitorPolicy.SampleInput(
                elapsedMs = 4_000,
                rxDelta = 1_712_752,
                txDelta = 126_208,
                handshakeAgeSec = 28,
                tunnelApiOk = false,
            ),
        )
        assertEquals(QualityMonitorPolicy.Verdict.SLOW, r.verdict)
        assertTrue(r.likelyCause.contains("tunnel_api_soft_fail"))
        assertTrue(QualityMonitorPolicy.isProblem(r.verdict))
    }

    @Test
    fun `escalate after two problems`() {
        assertFalse(QualityMonitorPolicy.shouldEscalate(1))
        assertTrue(QualityMonitorPolicy.shouldEscalate(2))
    }

    @Test
    fun `min active bytes scales with window`() {
        assertEquals(64L * 1024, QualityMonitorPolicy.minActiveBytesForWindow(60_000))
        assertEquals(8L * 1024, QualityMonitorPolicy.minActiveBytesForWindow(4_000))
        assertTrue(QualityMonitorPolicy.minActiveBytesForWindow(12_000) >= 8L * 1024)
    }

    @Test
    fun `public quality path is under Download SilentVPN`() {
        assertEquals(
            "quality-20260911-154812.jsonl",
            QualityMonitorPolicy.qualityFileName("20260911", "154812"),
        )
        assertEquals("Download/SilentVPN/", QualityMonitorPolicy.mediaStoreRelativePath())
        assertEquals(
            "/storage/emulated/0/Download/SilentVPN/quality-20260911-154812.jsonl",
            QualityMonitorPolicy.publicPathHint("quality-20260911-154812.jsonl"),
        )
        assertTrue(
            QualityMonitorPolicy.mediaStoreRelativePathCandidates()
                .any { it.contains("SilentVPN") },
        )
    }
}
