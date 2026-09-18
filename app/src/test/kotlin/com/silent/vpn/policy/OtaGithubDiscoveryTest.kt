package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class OtaGithubDiscoveryTest {

    private val json = """
        {
          "api_base": "https://89-125-188-100.nip.io",
          "android": {
            "version": "1.0.166",
            "filename": "SilentVPN-release-1.0.166.apk",
            "size": 27778447,
            "download_url": "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/SilentVPN-release-1.0.166.apk"
          },
          "pc": {
            "version": "1.0.166",
            "filename": "Silent.VPN.Setup.1.0.166.exe",
            "size": 83072897,
            "download_url": "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/Silent.VPN.Setup.1.0.166.exe"
          },
          "linux": {
            "version": "1.0.166",
            "filename": "Silent.VPN.Setup.1.0.166.deb",
            "size": 118399176,
            "download_url": "https://github.com/silentvpn3/silentvpn3.github.io/releases/download/v1.0.166/Silent.VPN.Setup.1.0.166.deb"
          }
        }
    """.trimIndent()

    @Test
    fun `releases json url is github pages not hive ip`() {
        assertEquals(
            "https://silentvpn3.github.io/releases.json",
            OtaGithubDiscovery.RELEASES_JSON_URL,
        )
        assertTrue(!OtaGithubDiscovery.RELEASES_JSON_URL.contains("nip.io"))
        assertTrue(!OtaGithubDiscovery.RELEASES_JSON_URL.contains("89.125"))
    }

    @Test
    fun `165 android sees 166 from github pages`() {
        val got = OtaGithubDiscovery.parse(json, platform = "android", currentVersion = "1.0.165")
        val offer = got as OtaGithubDiscovery.Result.Available
        assertEquals("1.0.166", offer.version)
        assertEquals("SilentVPN-release-1.0.166.apk", offer.filename)
        assertEquals(27778447L, offer.size)
        assertTrue(offer.downloadUrl.contains("github.com/silentvpn3"))
    }

    @Test
    fun `same version is current so hive ip outage cannot hide up-to-date`() {
        val got = OtaGithubDiscovery.parse(json, platform = "android", currentVersion = "1.0.166")
        assertEquals(OtaGithubDiscovery.Result.Current("1.0.166"), got)
    }

    @Test
    fun `garbage or missing json falls through to api`() {
        assertEquals(OtaGithubDiscovery.Result.Unreadable, OtaGithubDiscovery.parse(null, "android", "1.0.165"))
        assertEquals(OtaGithubDiscovery.Result.Unreadable, OtaGithubDiscovery.parse("{", "android", "1.0.165"))
        assertEquals(OtaGithubDiscovery.Result.Unreadable, OtaGithubDiscovery.parse("{}", "mac", "1.0.165"))
    }

    @Test
    fun `pc linux and tv map onto landing keys`() {
        val pc = OtaGithubDiscovery.parse(json, "pc", "1.0.165") as OtaGithubDiscovery.Result.Available
        val linux = OtaGithubDiscovery.parse(json, "linux", "1.0.165") as OtaGithubDiscovery.Result.Available
        val tv = OtaGithubDiscovery.parse(json, "android_tv", "1.0.165") as OtaGithubDiscovery.Result.Available
        assertTrue(pc.downloadUrl.endsWith(".exe"))
        assertTrue(linux.downloadUrl.endsWith(".deb"))
        assertTrue(tv.downloadUrl.endsWith(".apk"))
        assertEquals("android", OtaGithubDiscovery.landingKey("android_tv"))
        assertEquals("mac", OtaGithubDiscovery.landingKey("darwin"))
        assertEquals("pc", OtaGithubDiscovery.landingKey("windows"))
    }
}
