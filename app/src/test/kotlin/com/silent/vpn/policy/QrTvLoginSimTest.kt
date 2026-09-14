package com.silent.vpn.policy

import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.job
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Симуляция экрана входа на ТВ: qrStart через overlay, poll ждёт, телефон approve.
 * Это тот же сценарий, что «повторный скан — уже зареган, на ТВ ничего».
 */
class QrTvLoginSimTest {

    @Test
    fun `skip-if-active nested overlay never delivers tokens after phone approve`() = runTest {
        val out = QrTvLoginSim.run(
            join = OverlayJoinMode.SKIP_IF_ACTIVE,
            startPollInsideStartOverlay = true,
        )
        assertFalse(
            "баг прошлого APK: poll внутри qrStart, overlay гаснет, ТВ не видит approved",
            out.tvGotTokens,
        )
        assertTrue("poll успел стартовать, но ходил мимо туннеля", out.missedPolls > 0)
    }

    @Test
    fun `lease keeps hive route so nested tv poll sees phone approval`() = runTest {
        val out = QrTvLoginSim.run(
            join = OverlayJoinMode.LEASE,
            startPollInsideStartOverlay = true,
        )
        assertTrue(out.tvGotTokens)
        assertTrue(out.hivePolls > 0)
    }

    @Test
    fun `poll after qrStart overlay delivers tokens even with skip-if-active`() = runTest {
        val out = QrTvLoginSim.run(
            join = OverlayJoinMode.SKIP_IF_ACTIVE,
            startPollInsideStartOverlay = false,
        )
        assertTrue(out.tvGotTokens)
        assertTrue(out.hivePolls > 0)
    }

    @Test
    fun `nested lease still routed after parent overlay exits`() {
        var state = ApiOverlayLease.State()
        val start = ApiOverlayLease.begin(state)
        state = start.first
        assertTrue(start.second)
        val child = ApiOverlayLease.begin(state)
        state = child.first
        assertTrue(!child.second)
        val parentExit = ApiOverlayLease.end(state)
        state = parentExit.first
        assertTrue(!parentExit.second)
        assertTrue(state.active)
        val childExit = ApiOverlayLease.end(state)
        assertTrue(childExit.second)
        assertTrue(!childExit.first.active)
    }

    @Test
    fun `cancelling poll job before goToMain leaves tv on login`() = runTest {
        var onMain = false
        val job = launch {
            coroutineContext.job.cancel()
            yield()
            onMain = true
        }
        job.join()
        assertFalse("баг: completeLoginFromTokens звал qrPollJob.cancel() на себе", onMain)
    }

    @Test
    fun `after tokens navigate even when running on the poll job`() = runTest {
        var onMain = false
        val job = launch {
            onMain = true
        }
        job.join()
        assertTrue(onMain)
        assertTrue(job.isCompleted)
        assertTrue(!job.isCancelled)
    }
}

private enum class OverlayJoinMode { SKIP_IF_ACTIVE, LEASE }

private data class QrTvSimOutcome(
    val tvGotTokens: Boolean,
    val hivePolls: Int,
    val missedPolls: Int,
)

private object QrTvLoginSim {
    suspend fun run(
        join: OverlayJoinMode,
        startPollInsideStartOverlay: Boolean,
        tickMs: Long = 1,
    ): QrTvSimOutcome = coroutineScope {
        val overlay = FakeBootstrapOverlay(join)
        var approved = false
        var gotTokens = false
        var hivePolls = 0
        var missedPolls = 0

        suspend fun pollLoop() {
            overlay.withOverlay {
                repeat(16) {
                    if (overlay.hiveRouted) {
                        hivePolls++
                        if (approved) {
                            gotTokens = true
                            return@withOverlay
                        }
                    } else {
                        missedPolls++
                    }
                    delay(tickMs)
                }
            }
        }

        overlay.withOverlay {
            check(overlay.hiveRouted) { "qrStart must go through hive" }
            if (startPollInsideStartOverlay) {
                launch { pollLoop() }
                yield()
                delay(tickMs)
            }
        }
        if (!startPollInsideStartOverlay) {
            launch { pollLoop() }
            yield()
            delay(tickMs)
        }
        approved = true
        delay(tickMs * 10)
        QrTvSimOutcome(gotTokens, hivePolls, missedPolls)
    }
}

private class FakeBootstrapOverlay(private val join: OverlayJoinMode) {
    var hiveRouted: Boolean = false
        private set
    private var lease = ApiOverlayLease.State()
    private var skipActive = false

    suspend fun <T> withOverlay(block: suspend () -> T): T {
        when (join) {
            OverlayJoinMode.SKIP_IF_ACTIVE -> {
                if (skipActive) return block()
                skipActive = true
                hiveRouted = true
                try {
                    return block()
                } finally {
                    skipActive = false
                    hiveRouted = false
                }
            }
            OverlayJoinMode.LEASE -> {
                val (next, enter) = ApiOverlayLease.begin(lease)
                lease = next
                if (enter) hiveRouted = true
                try {
                    return block()
                } finally {
                    val (after, restore) = ApiOverlayLease.end(lease)
                    lease = after
                    if (restore) hiveRouted = false
                }
            }
        }
    }
}
