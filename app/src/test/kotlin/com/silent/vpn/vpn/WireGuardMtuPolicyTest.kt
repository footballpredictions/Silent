package com.silent.vpn.vpn

import com.silent.vpn.data.VpnConfig
import org.junit.Assert.assertEquals
import org.junit.Test

class WireGuardMtuPolicyTest {
    private fun cfg(slot: String?, ip: String) = VpnConfig(
        device_id = "d",
        wg_private_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        wg_address = "10.66.0.2/32",
        wg_dns = "1.1.1.1",
        server_ip = ip,
        server_port = 56000,
        server_public_key = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        wdtt_password = "x",
        vk_hashes = emptyList(),
        stream_count = 1,
        selected_server = slot,
    )

    @Test
    fun server3_gets_game_mtu() {
        assertEquals(1420, WireGuardConfigBuilder.mtuForConfig(cfg("server3", "78.17.74.27")))
        assertEquals(1420, WireGuardConfigBuilder.mtuForConfig(cfg(null, "78.17.74.27")))
        assertEquals(1420, WireGuardConfigBuilder.mtuForSlotAndIp("server3", "1.2.3.4"))
    }

    @Test
    fun other_slots_keep_default_mtu_not_server_1280() {
        assertEquals(1200, WireGuardConfigBuilder.mtuForConfig(cfg("server1", "89.125.188.100")))
        assertEquals(1200, WireGuardConfigBuilder.mtuForConfig(cfg("server2", "87.58.213.193")))
        assertEquals(1200, WireGuardConfigBuilder.mtuForConfig(cfg("server4", "192.177.26.38")))
        // GETCONF часто шлёт 1280 — клиентская политика всё равно 1200 вне server3
        assertEquals(1200, WireGuardConfigBuilder.mtuForSlotAndIp("server1", null))
    }
}
