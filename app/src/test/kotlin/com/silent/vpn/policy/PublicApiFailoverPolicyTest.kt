package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class PublicApiFailoverPolicyTest {

    @Test
    fun `cells first so blocked hive 443 does not stall splash and toggle`() {
        val got = PublicApiFailoverPolicy.orderedPublicBases(
            hiveHttps = listOf(
                "https://89-125-188-100.nip.io",
                "https://89.125.188.100",
            ),
            cells = listOf(
                "http://87.58.213.193:9100",
                "http://78.17.74.27:9100",
            ),
        )
        assertEquals(
            listOf(
                "http://87.58.213.193:9100",
                "http://78.17.74.27:9100",
                "https://89-125-188-100.nip.io",
                "https://89.125.188.100",
            ),
            got,
        )
    }

    @Test
    fun `splash still tries public cells before hive bootstrap vpn`() {
        assertFalse(ConnectConfigFetchPolicy.skipPublicFailover(onMobile = false, forLaunch = true))
        assertFalse(ConnectConfigFetchPolicy.skipPublicFailover(onMobile = true, forLaunch = true))
        assertFalse(ConnectConfigFetchPolicy.skipPublicFailover(onMobile = false, forLaunch = false))
    }

    @Test
    fun `timeout and 5xx try next base, 4xx from live api do not`() {
        assertEquals(true, PublicApiFailoverPolicy.shouldTryNextBase(null))
        assertEquals(true, PublicApiFailoverPolicy.shouldTryNextBase(0))
        assertEquals(true, PublicApiFailoverPolicy.shouldTryNextBase(408))
        assertEquals(true, PublicApiFailoverPolicy.shouldTryNextBase(502))
        assertEquals(false, PublicApiFailoverPolicy.shouldTryNextBase(200))
        assertEquals(false, PublicApiFailoverPolicy.shouldTryNextBase(400))
        assertEquals(false, PublicApiFailoverPolicy.shouldTryNextBase(401))
        assertEquals(false, PublicApiFailoverPolicy.shouldTryNextBase(402))
    }

    @Test
    fun `https hive gets a short connect timeout so cells are reached`() {
        assertEquals(4L, PublicApiFailoverPolicy.connectTimeoutSec("https://89-125-188-100.nip.io"))
        assertEquals(8L, PublicApiFailoverPolicy.connectTimeoutSec("http://87.58.213.193:9100"))
    }
}
