package com.silent.vpn.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class QrLoginPayloadTest {
    @Test
    fun roundtripSession() {
        val uri = buildQrPayload(QrLoginPayload.KIND_SESSION, "Abc_123-token")
        assertEquals("silentvpn://qr?k=s&c=Abc_123-token", uri)
        val parsed = parseQrPayload(uri)!!
        assertTrue(parsed.isSession)
        assertEquals("Abc_123-token", parsed.code)
    }

    @Test
    fun roundtripUser() {
        val parsed = parseQrPayload(buildQrPayload(QrLoginPayload.KIND_USER, "userCode99"))!!
        assertTrue(parsed.isUser)
        assertEquals("userCode99", parsed.code)
    }

    @Test
    fun ignoresOtherLinks() {
        assertNull(parseQrPayload("silentvpn://ref?code=ABCD"))
        assertNull(parseQrPayload("https://example.com/login?k=s&c=xxxxxx12"))
        assertNull(parseQrPayload("silentvpn://qr?k=s&c="))
        assertNull(parseQrPayload("silentvpn://qr?k=x&c=abcdefgh"))
    }

    @Test
    fun findsUriInsideNoisyScan() {
        val parsed = parseQrPayload("  extra SILENTVPN://qr?k=s&c=Abc_123-token tail")!!
        assertTrue(parsed.isSession)
        assertEquals("Abc_123-token", parsed.code)
        assertEquals("silentvpn://qr?k=s&c=Abc_123-token", parsed.toUri())
    }

    @Test
    fun parsesHttpsLandingFromExternalScanner() {
        val parsed = parseQrPayload("https://89-125-188-100.nip.io/qr?k=s&c=Abc_123-token")!!
        assertTrue(parsed.isSession)
        assertEquals("Abc_123-token", parsed.code)
        assertEquals("silentvpn://qr?k=s&c=Abc_123-token", parsed.toUri())
    }

    @Test
    fun keepsMainVpnForQrApprove() {
        assertTrue(qrApproveKeepsExistingVpn(mainVpnUp = true, serviceRunning = true, bootstrapMode = false))
        assertTrue(qrApproveKeepsExistingVpn(mainVpnUp = false, serviceRunning = true, bootstrapMode = false))
        assertTrue(!qrApproveKeepsExistingVpn(mainVpnUp = false, serviceRunning = false, bootstrapMode = false))
        assertTrue(!qrApproveKeepsExistingVpn(mainVpnUp = false, serviceRunning = true, bootstrapMode = true))
    }

    @Test
    fun keepsWaitingQrUnlessRefreshOrExpired() {
        assertTrue(
            shouldReuseQrWaitingSession(
                forceRefresh = false,
                token = "Abc_123-token",
                payload = "silentvpn://qr?k=s&c=Abc_123-token",
                expired = false,
            ),
        )
        assertTrue(
            !shouldReuseQrWaitingSession(
                forceRefresh = true,
                token = "Abc_123-token",
                payload = "silentvpn://qr?k=s&c=Abc_123-token",
                expired = false,
            ),
        )
        assertTrue(
            !shouldReuseQrWaitingSession(
                forceRefresh = false,
                token = "Abc_123-token",
                payload = "silentvpn://qr?k=s&c=Abc_123-token",
                expired = true,
            ),
        )
        assertTrue(
            !shouldReuseQrWaitingSession(
                forceRefresh = false,
                token = "",
                payload = "",
                expired = false,
            ),
        )
    }

    @Test
    fun poll403AfterPhoneApproveIsFatalNotSilentRetry() {
        val decision = interpretQrPoll(
            httpCode = 403,
            status = null,
            accessToken = null,
            refreshToken = null,
            errorText = "Достигнут лимит 3 устройств",
        )
        assertTrue(decision is QrPollDecision.Failed)
        assertEquals("Достигнут лимит 3 устройств", (decision as QrPollDecision.Failed).message)
    }

    @Test
    fun pollApprovedWithoutTokensIsFatal() {
        val decision = interpretQrPoll(
            httpCode = 200,
            status = "approved",
            accessToken = null,
            refreshToken = null,
            errorText = null,
        )
        assertTrue(decision is QrPollDecision.Failed)
    }

    @Test
    fun pollApprovedWithTokensLogsIn() {
        val decision = interpretQrPoll(
            httpCode = 200,
            status = "approved",
            accessToken = "a",
            refreshToken = "r",
            errorText = null,
        )
        val ok = decision as QrPollDecision.Approved
        assertEquals("a", ok.access)
        assertEquals("r", ok.refresh)
    }
}
