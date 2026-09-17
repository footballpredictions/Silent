package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiHostHeaderPolicyTest {

    @Test
    fun tunnelGatewayKeepsOwnHostSoCellNginxDoesNotRedirectPost() {
        assertFalse(ApiHostHeaderPolicy.shouldSetNipIoHost("10.66.66.1"))
        assertEquals(null, ApiHostHeaderPolicy.nipIoHostHeader("10.66.66.1"))
    }

    @Test
    fun loopbackAndHostnameSkipNipIoHost() {
        assertFalse(ApiHostHeaderPolicy.shouldSetNipIoHost("127.0.0.1"))
        assertFalse(ApiHostHeaderPolicy.shouldSetNipIoHost("132-243-234-162.nip.io"))
        assertEquals(null, ApiHostHeaderPolicy.nipIoHostHeader("localhost"))
    }

    @Test
    fun publicHiveIpStillSendsNipIoHostForTlsVhost() {
        assertTrue(ApiHostHeaderPolicy.shouldSetNipIoHost("132.243.234.162"))
        assertEquals(
            VpnNetworkConstants.DEFAULT_SERVER_HOST,
            ApiHostHeaderPolicy.nipIoHostHeader("132.243.234.162"),
        )
    }

    @Test
    fun cellPublicIpKeepsNipIoHostForHttpsByIp() {
        assertTrue(ApiHostHeaderPolicy.shouldSetNipIoHost("87.58.213.193"))
    }
}
