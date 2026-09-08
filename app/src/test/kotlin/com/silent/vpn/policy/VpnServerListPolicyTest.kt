package com.silent.vpn.policy

import com.silent.vpn.data.VpnServerInfo
import com.silent.vpn.policy.VpnServerListPolicy
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class VpnServerListPolicyTest {

    @Test
    fun `static list is four slots including ai title without waiting for api`() {
        val list = VpnServerListPolicy.displayList(emptyList())
        assertEquals(listOf("server1", "server2", "server3", "server4"), list.map { it.key })
        assertEquals("Сервер 4 для ИИ", list.last().title)
    }

    @Test
    fun `api with only three servers still keeps the ai slot`() {
        val api = listOf(
            VpnServerInfo(key = "server1", title = "Сервер 1"),
            VpnServerInfo(key = "server2", title = "Сервер 2"),
            VpnServerInfo(key = "server3", title = "Сервер 3"),
        )
        val list = VpnServerListPolicy.displayList(api)
        assertEquals(4, list.size)
        assertTrue(list.any { it.key == "server4" && it.title == "Сервер 4 для ИИ" })
    }

    @Test
    fun `api title for ai slot wins over the stub`() {
        val api = listOf(
            VpnServerInfo(key = "server4", title = "Сервер 4 для ИИ", public_ip = "1.2.3.4"),
        )
        val list = VpnServerListPolicy.displayList(api)
        val ai = list.first { it.key == "server4" }
        assertEquals("1.2.3.4", ai.public_ip)
        assertEquals("Сервер 4 для ИИ", ai.title)
    }
}
