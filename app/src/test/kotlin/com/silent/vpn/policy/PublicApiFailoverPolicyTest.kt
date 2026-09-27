package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PublicApiFailoverPolicyTest {

    @Test
    fun `hive first then cell 1 then the next cell`() {
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
                "https://89.125.188.100",
                "http://87.58.213.193:9100",
                "http://78.17.74.27:9100",
                "https://89-125-188-100.nip.io",
            ),
            got,
        )
    }

    @Test
    fun `open internet still requests every server slot even when cache exists`() {
        assertEquals(
            listOf("server1", "server2", "server3", "server4", "server5"),
            ConnectConfigFetchPolicy.launchConfigSlots(
                alreadyCached = listOf("server1", "server2", "server3", "server4", "server5"),
            ),
        )
    }

    @Test
    fun `successful config replaces the saved one even when the ip was not known yet`() {
        assertTrue(
            ConnectConfigFetchPolicy.shouldPersistFetchedConfig(
                connectable = true,
                ipMatchesSlot = false,
            ),
        )
        assertFalse(
            ConnectConfigFetchPolicy.shouldPersistFetchedConfig(
                connectable = false,
                ipMatchesSlot = true,
            ),
        )
    }

    @Test
    fun `late bootstrap still fetches configs once before it is stopped`() {
        assertTrue(
            ConnectConfigFetchPolicy.fetchConfigsBeforeStoppingBootstrap(
                tunnelReady = true,
                configsAlreadySaved = false,
            ),
        )
        assertFalse(
            ConnectConfigFetchPolicy.fetchConfigsBeforeStoppingBootstrap(
                tunnelReady = true,
                configsAlreadySaved = true,
            ),
        )
        assertFalse(
            ConnectConfigFetchPolicy.fetchConfigsBeforeStoppingBootstrap(
                tunnelReady = false,
                configsAlreadySaved = false,
            ),
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
    fun `stored old hive ip is rewritten to current nip and never tried`() {
        val nip = "https://89-125-188-100.nip.io"
        assertEquals(
            nip,
            PublicApiFailoverPolicy.rewriteStoredBase("https://132.243.234.162", nip),
        )
        assertEquals(
            nip,
            PublicApiFailoverPolicy.rewriteStoredBase("https://132-243-234-162.nip.io", nip),
        )
        assertEquals(
            nip,
            PublicApiFailoverPolicy.rewriteStoredBase("https://89.125.188.100", nip),
        )
        val got = PublicApiFailoverPolicy.orderedPublicBases(
            hiveHttps = listOf("https://132.243.234.162", nip),
            cells = listOf("http://87.58.213.193:9100"),
        )
        assertEquals(listOf("http://87.58.213.193:9100", nip), got)
    }

    @Test
    fun `https hive gets a short connect timeout so cells are reached`() {
        assertEquals(4L, PublicApiFailoverPolicy.connectTimeoutSec("https://89-125-188-100.nip.io"))
        assertEquals(8L, PublicApiFailoverPolicy.connectTimeoutSec("http://87.58.213.193:9100"))
    }
}
