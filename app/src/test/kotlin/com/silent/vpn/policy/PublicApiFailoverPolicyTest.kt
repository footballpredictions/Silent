package com.silent.vpn.policy

import org.junit.Assert.assertEquals
import org.junit.Test

class PublicApiFailoverPolicyTest {

    @Test
    fun `hive https first then cells in order`() {
        val got = PublicApiFailoverPolicy.orderedPublicBases(
            hiveHttps = listOf(
                "https://132-243-234-162.nip.io",
                "https://132.243.234.162",
            ),
            cells = listOf(
                "http://87.58.213.193:9100",
                "http://78.17.74.27:9100",
            ),
        )
        assertEquals(
            listOf(
                "https://132-243-234-162.nip.io",
                "https://132.243.234.162",
                "http://87.58.213.193:9100",
                "http://78.17.74.27:9100",
            ),
            got,
        )
    }
}
