package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Автотесты логики olcrtc: первый connect на LTE, Wi‑Fi↔cell,
 * peer closed, watchdog, prefetch после stop, await сети.
 */
class OlcrtcRecoveryPolicyTest {

    private fun recover(
        everReady: Boolean = true,
        reason: String = "transport_switch:mobile",
        prefer: String? = "cell",
        inFlight: Boolean = false,
        running: Boolean = true,
        cfg: String? = """{"bypass_family":"olcrtc"}""",
        lastSwitchTarget: String = "",
        lastSwitchMs: Long = 0L,
        lastRestartMs: Long = 0L,
        now: Long = 100_000L,
    ) = OlcrtcRecoveryPolicy.decideRecover(
        OlcrtcRecoveryPolicy.RecoverInput(
            configJson = cfg,
            isRunning = running,
            everReady = everReady,
            recoverInFlight = inFlight,
            reason = reason,
            preferFromReason = prefer,
            lastTransportSwitchTarget = lastSwitchTarget,
            lastTransportSwitchMs = lastSwitchMs,
            lastTransportRestartMs = lastRestartMs,
            nowMs = now,
        ),
    )

    @Test
    fun `initial connect grace blocks recover until everReady`() {
        assertTrue(
            OlcrtcRecoveryPolicy.isInitialConnectInProgress(
                OlcrtcRecoveryPolicy.InitialConnectInput(
                    sessionActive = true,
                    everReady = false,
                    isRunning = true,
                    connectStartedAtMs = 0L,
                    nowMs = 30_000L,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.isInitialConnectInProgress(
                OlcrtcRecoveryPolicy.InitialConnectInput(
                    sessionActive = true,
                    everReady = true,
                    isRunning = true,
                    connectStartedAtMs = 0L,
                    nowMs = 30_000L,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.isInitialConnectInProgress(
                OlcrtcRecoveryPolicy.InitialConnectInput(
                    sessionActive = true,
                    everReady = false,
                    isRunning = true,
                    connectStartedAtMs = 0L,
                    nowMs = OlcrtcRecoveryPolicy.CONNECT_GRACE_MS + 1,
                ),
            ),
        )
    }

    @Test
    fun `LTE first connect never starts recover before ready`() {
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            recover(everReady = false, reason = "validated", prefer = null),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            recover(everReady = false, reason = "transport_switch:mobile", prefer = "cell"),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            recover(everReady = false, reason = "internet_restored", prefer = null),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            recover(everReady = false, reason = "watchdog_olcrtc_down", prefer = null),
        )
    }

    @Test
    fun `after ready allow wifi to mobile transport switch`() {
        assertEquals(
            "cell",
            OlcrtcRecoveryPolicy.preferTransportFromReason("transport_switch:mobile"),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                everReady = true,
                reason = "transport_switch:mobile",
                prefer = "cell",
            ),
        )
    }

    @Test
    fun `after ready allow mobile to wifi transport switch`() {
        assertEquals(
            "wifi",
            OlcrtcRecoveryPolicy.preferTransportFromReason("transport_switch:wifi"),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                everReady = true,
                reason = "transport_switch:wifi",
                prefer = "wifi",
            ),
        )
    }

    @Test
    fun `duplicate transport switch within dedup window skipped`() {
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_SWITCH_DUP,
            recover(
                prefer = "cell",
                lastSwitchTarget = "cell",
                lastSwitchMs = 90_000L,
                now = 100_000L, // 10s < 25s
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                prefer = "cell",
                lastSwitchTarget = "cell",
                lastSwitchMs = 70_000L,
                now = 100_000L, // 30s > 25s
            ),
        )
    }

    @Test
    fun `recover debounce skips peer_dead but allows restore and retry`() {
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_DEBOUNCE,
            recover(
                reason = "olcrtc_peer_dead:peer_closed",
                prefer = null,
                lastRestartMs = 95_000L,
                now = 100_000L,
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                reason = "internet_restored",
                prefer = null,
                lastRestartMs = 95_000L,
                now = 100_000L,
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                reason = "olcrtc_peer_dead:peer_closed:retry",
                prefer = null,
                lastRestartMs = 95_000L,
                now = 100_000L,
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                reason = "phone_call_end",
                prefer = null,
                lastRestartMs = 95_000L,
                now = 100_000L,
            ),
        )
    }

    @Test
    fun `in-flight recover is not cancelled by second signal`() {
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_IN_FLIGHT,
            recover(inFlight = true, prefer = "wifi"),
        )
    }

    @Test
    fun `retry only once after failed recover`() {
        assertTrue(
            OlcrtcRecoveryPolicy.shouldScheduleRecoverRetry(
                everReady = true,
                reason = "transport_switch:mobile",
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldScheduleRecoverRetry(
                everReady = true,
                reason = "transport_switch:mobile:retry",
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldScheduleRecoverRetry(
                everReady = false,
                reason = "transport_switch:mobile",
            ),
        )
    }

    @Test
    fun `LTE recover uses cache without nip fetch`() {
        assertFalse(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = true,
                reason = "olcrtc_peer_dead:peer_closed",
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = true,
                reason = "watchdog_olcrtc_down",
            ),
        )
        assertTrue(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = false,
                reason = "olcrtc_peer_dead:peer_closed",
            ),
        )
        assertTrue(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = false,
                reason = "watchdog_olcrtc_socks",
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldRefreshConfigOnRecover(
                onMobileData = false,
                reason = "transport_switch:wifi",
            ),
        )
    }

    @Test
    fun `watchdog silent during initial connect and starting`() {
        val base = OlcrtcRecoveryPolicy.WatchdogInput(
            sessionActive = true,
            running = false,
            tunnelReady = false,
            recoverInFlight = false,
            initialConnectInProgress = true,
            starting = false,
            withinLibclientConnectGrace = false,
            sinceRestartMs = 60_000L,
            socksHealthy = false,
        )
        assertEquals(OlcrtcRecoveryPolicy.WatchdogAction.NONE, OlcrtcRecoveryPolicy.decideWatchdog(base))
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.NONE,
            OlcrtcRecoveryPolicy.decideWatchdog(base.copy(initialConnectInProgress = false, starting = true)),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.NONE,
            OlcrtcRecoveryPolicy.decideWatchdog(base.copy(initialConnectInProgress = false, recoverInFlight = true)),
        )
    }

    @Test
    fun `watchdog stuck down and socks variants`() {
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.STUCK,
            OlcrtcRecoveryPolicy.decideWatchdog(
                OlcrtcRecoveryPolicy.WatchdogInput(
                    sessionActive = true,
                    running = true,
                    tunnelReady = false,
                    recoverInFlight = false,
                    initialConnectInProgress = false,
                    starting = false,
                    withinLibclientConnectGrace = false,
                    sinceRestartMs = OlcrtcRecoveryPolicy.WATCHDOG_STUCK_MS + 1,
                    socksHealthy = true,
                ),
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.DOWN,
            OlcrtcRecoveryPolicy.decideWatchdog(
                OlcrtcRecoveryPolicy.WatchdogInput(
                    sessionActive = true,
                    running = false,
                    tunnelReady = false,
                    recoverInFlight = false,
                    initialConnectInProgress = false,
                    starting = false,
                    withinLibclientConnectGrace = false,
                    sinceRestartMs = OlcrtcRecoveryPolicy.WATCHDOG_DOWN_MS + 1,
                    socksHealthy = false,
                ),
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.SOCKS_DEAD,
            OlcrtcRecoveryPolicy.decideWatchdog(
                OlcrtcRecoveryPolicy.WatchdogInput(
                    sessionActive = true,
                    running = true,
                    tunnelReady = true,
                    recoverInFlight = false,
                    initialConnectInProgress = false,
                    starting = false,
                    withinLibclientConnectGrace = false,
                    sinceRestartMs = OlcrtcRecoveryPolicy.WATCHDOG_SOCKS_MS + 1,
                    socksHealthy = false,
                ),
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.WatchdogAction.NONE,
            OlcrtcRecoveryPolicy.decideWatchdog(
                OlcrtcRecoveryPolicy.WatchdogInput(
                    sessionActive = true,
                    running = true,
                    tunnelReady = true,
                    recoverInFlight = false,
                    initialConnectInProgress = false,
                    starting = false,
                    withinLibclientConnectGrace = false,
                    sinceRestartMs = OlcrtcRecoveryPolicy.WATCHDOG_SOCKS_MS + 1,
                    socksHealthy = true,
                ),
            ),
        )
    }

    @Test
    fun `peer closed grace self-heal vs restart`() {
        assertFalse(
            OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                    running = true,
                    iceConnected = true,
                    socksHealthy = false,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                    running = true,
                    iceConnected = false,
                    socksHealthy = true,
                ),
            ),
        )
        assertTrue(
            OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                    running = true,
                    iceConnected = false,
                    socksHealthy = false,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                    running = false,
                    iceConnected = false,
                    socksHealthy = false,
                ),
            ),
        )
    }

    @Test
    fun `prefetch must not reuse after stop and must expire`() {
        assertTrue(OlcrtcRecoveryPolicy.shouldInvalidatePrefetchOnStop())

        assertTrue(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = "room-1",
                    requestRoom = "room-1",
                    untilMs = 200_000L,
                    nowMs = 100_000L,
                    fileExists = true,
                ),
            ),
        )
        // После stop кэш null → reuse false (это чинит media timeout на recover).
        assertFalse(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = null,
                    requestRoom = "room-1",
                    untilMs = 200_000L,
                    nowMs = 100_000L,
                    fileExists = true,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = "room-1",
                    requestRoom = "room-1",
                    untilMs = 90_000L,
                    nowMs = 100_000L,
                    fileExists = true,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = "room-old",
                    requestRoom = "room-1",
                    untilMs = 200_000L,
                    nowMs = 100_000L,
                    fileExists = true,
                ),
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = "room-1",
                    requestRoom = "room-1",
                    untilMs = 200_000L,
                    nowMs = 100_000L,
                    fileExists = false,
                ),
            ),
        )
    }

    @Test
    fun `await underlying ready LTE airplane and prefer hold`() {
        // Prefer cell, validated cell — сразу ok.
        assertTrue(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 100L,
                    fingerprint = "cell",
                    validated = true,
                    anyInternet = true,
                    preferTransport = "cell",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
        // Prefer wifi, но уже cell и hold ещё не вышел — не ok (ждём wifi).
        assertFalse(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 1_000L,
                    fingerprint = "cell",
                    validated = true,
                    anyInternet = true,
                    preferTransport = "wifi",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
        // После preferHold — принимаем любой validated (самолётик → LTE, wifi уже нет).
        assertTrue(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 3_600L,
                    fingerprint = "cell",
                    validated = true,
                    anyInternet = true,
                    preferTransport = "wifi",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
        // LTE без VALIDATED: any internet после 1.2с + preferHold.
        assertFalse(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 1_500L,
                    fingerprint = "cell",
                    validated = false,
                    anyInternet = true,
                    preferTransport = "cell",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
        assertTrue(
            OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReady(
                OlcrtcRecoveryPolicy.UnderlyingReadySample(
                    elapsedMs = 3_600L,
                    fingerprint = "cell",
                    validated = false,
                    anyInternet = true,
                    preferTransport = "cell",
                    preferHoldMs = 3_500L,
                ),
            ),
        )
        assertTrue(OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReadyOnTimeout(anyInternet = true))
        assertFalse(OlcrtcRecoveryPolicy.shouldAcceptUnderlyingReadyOnTimeout(anyInternet = false))
    }

    @Test
    fun `skip all network recovery during initial connect including switch`() {
        assertTrue(
            OlcrtcRecoveryPolicy.shouldSkipNetworkRecoveryDuringInitialConnect(
                initialConnectInProgress = true,
                reason = "transport_switch:mobile",
            ),
        )
        assertTrue(
            OlcrtcRecoveryPolicy.shouldSkipNetworkRecoveryDuringInitialConnect(
                initialConnectInProgress = true,
                reason = "validated",
            ),
        )
        assertFalse(
            OlcrtcRecoveryPolicy.shouldSkipNetworkRecoveryDuringInitialConnect(
                initialConnectInProgress = false,
                reason = "transport_switch:mobile",
            ),
        )
    }

    @Test
    fun `wifi cell targets match NetworkRecoveryPolicy`() {
        assertEquals(
            NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "cell"),
            "mobile",
        )
        assertEquals(
            OlcrtcRecoveryPolicy.preferTransportFromReason(
                "transport_switch:${NetworkRecoveryPolicy.wifiCellTransportTarget("wifi", "cell")}",
            ),
            "cell",
        )
        assertEquals(
            OlcrtcRecoveryPolicy.preferTransportFromReason(
                "transport_switch:${NetworkRecoveryPolicy.wifiCellTransportTarget("cell", "wifi")}",
            ),
            "wifi",
        )
    }

    @Test
    fun `full LTE connect then switch scenario matrix`() {
        // 1) Connect start
        var everReady = false
        val connectAt = 0L
        assertTrue(
            OlcrtcRecoveryPolicy.isInitialConnectInProgress(
                OlcrtcRecoveryPolicy.InitialConnectInput(
                    sessionActive = true,
                    everReady = everReady,
                    isRunning = true,
                    connectStartedAtMs = connectAt,
                    nowMs = 20_000L,
                ),
            ),
        )
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.SKIP_NEVER_READY,
            recover(everReady = false, reason = "capabilities:cell", prefer = null),
        )

        // 2) tunnelReady
        everReady = true
        assertFalse(
            OlcrtcRecoveryPolicy.isInitialConnectInProgress(
                OlcrtcRecoveryPolicy.InitialConnectInput(
                    sessionActive = true,
                    everReady = everReady,
                    isRunning = true,
                    connectStartedAtMs = connectAt,
                    nowMs = 40_000L,
                ),
            ),
        )

        // 3) Wi‑Fi→LTE
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                everReady = true,
                reason = "transport_switch:mobile",
                prefer = "cell",
                now = 50_000L,
            ),
        )

        // 4) peer closed → recover
        assertEquals(
            OlcrtcRecoveryPolicy.RecoverDecision.ALLOW,
            recover(
                everReady = true,
                reason = "olcrtc_peer_dead:peer_closed",
                prefer = null,
                lastRestartMs = 0L,
                now = 80_000L,
            ),
        )

        // 5) после stop prefetch reuse запрещён
        assertFalse(
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = null,
                    requestRoom = "41676137683602",
                    untilMs = Long.MAX_VALUE,
                    nowMs = 80_000L,
                    fileExists = false,
                ),
            ),
        )
    }
}
