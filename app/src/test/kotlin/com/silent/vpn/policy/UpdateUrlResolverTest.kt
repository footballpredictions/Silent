package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateUrlResolverTest {

    private fun baseInput(
        onMobileData: Boolean = false,
        mainVpnTunnelUp: Boolean = false,
        isBootstrapMode: Boolean = false,
        publicServerUrl: String = "https://132-243-234-162.nip.io",
    ) = UpdateUrlResolver.OtaUrlInput(
        onMobileData = onMobileData,
        appExcludedFromVpn = true,
        mainVpnTunnelUp = mainVpnTunnelUp,
        isBootstrapMode = isBootstrapMode,
        publicServerUrl = publicServerUrl,
    )

    @Test
    fun `wifi prefers github download url`() {
        val url = UpdateUrlResolver.resolveUpdateDownloadUrl(
            baseInput().copy(
                githubDownloadUrl = "https://github.com/silentvpn3/releases/apk.apk",
                downloadUrl = "/api/updates/download/android",
            ),
        )
        assertEquals("https://github.com/silentvpn3/releases/apk.apk", url)
    }

    @Test
    fun `lte vpn uses tunnel download path`() {
        val url = UpdateUrlResolver.resolveUpdateDownloadUrl(
            baseInput(onMobileData = true, mainVpnTunnelUp = true).copy(
                tunnelDownloadPath = "/api/updates/download/android",
                githubDownloadUrl = "https://github.com/ignored.apk",
            ),
        )
        assertEquals("http://10.66.66.1:8000/api/updates/download/android", url)
    }

    @Test
    fun `lte vpn default tunnel path when field missing`() {
        val url = UpdateUrlResolver.resolveUpdateDownloadUrl(
            baseInput(onMobileData = true, mainVpnTunnelUp = true).copy(otaPlatform = "android_tv"),
        )
        assertEquals("http://10.66.66.1:8000/api/updates/download/android_tv", url)
    }

    @Test
    fun `shouldUseTunnelUpdateDownload false on wifi`() {
        assertFalse(UpdateUrlResolver.shouldUseTunnelUpdateDownload(baseInput()))
    }

    @Test
    fun `shouldUseTunnelUpdateDownload false during bootstrap`() {
        assertFalse(
            UpdateUrlResolver.shouldUseTunnelUpdateDownload(
                baseInput(onMobileData = true, mainVpnTunnelUp = true, isBootstrapMode = true),
            ),
        )
    }

    @Test
    fun `shouldUseTunnelUpdateDownload true on lte excluded vpn`() {
        assertTrue(
            UpdateUrlResolver.shouldUseTunnelUpdateDownload(
                baseInput(onMobileData = true, mainVpnTunnelUp = true),
            ),
        )
    }

    @Test
    fun `resolveUpdateDownloadBase wifi uses preferred https`() {
        val base = UpdateUrlResolver.resolveUpdateDownloadBase(
            baseInput().copy(preferredHttpsBase = "https://cdn.example.com"),
        )
        assertEquals("https://cdn.example.com", base)
    }

    @Test
    fun `resolveUpdateDownloadBase lte vpn uses tunnel gateway`() {
        val base = UpdateUrlResolver.resolveUpdateDownloadBase(
            baseInput(onMobileData = true, mainVpnTunnelUp = true),
        )
        assertEquals("http://10.66.66.1:8000", base)
    }

    @Test
    fun `joinUpdateUrl encodes spaces`() {
        assertEquals(
            "https://host/file%20name.apk",
            UpdateUrlResolver.joinUpdateUrl("https://host", "/file name.apk"),
        )
    }

    @Test
    fun `isTunnelApiBase detects gateway and localhost proxy`() {
        assertTrue(UpdateUrlResolver.isTunnelApiBase("http://10.66.66.1:8000"))
        assertTrue(UpdateUrlResolver.isTunnelApiBase("http://127.0.0.1:9000/api"))
        assertFalse(UpdateUrlResolver.isTunnelApiBase("https://132-243-234-162.nip.io"))
    }

    @Test
    fun `relative download url joined with public base on wifi`() {
        val url = UpdateUrlResolver.resolveUpdateDownloadUrl(
            baseInput().copy(downloadUrl = "/files/app.apk"),
        )
        assertEquals("https://132-243-234-162.nip.io/files/app.apk", url)
    }

    @Test
    fun `blank relative download returns null`() {
        assertNull(UpdateUrlResolver.resolveUpdateDownloadUrl(baseInput().copy(downloadUrl = "  ")))
    }
}
