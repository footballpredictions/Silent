package com.silent.vpn.vpn

import com.silent.vpn.util.DebugLog
import java.net.InetAddress

/**
 * IP VK API / login / captcha — вне AllowedIPs WG.
 * libclient (нативный процесс) ходит в api.vk.ru напрямую, иначе после подъёма WG
 * getAnonymousToken идёт через туннель → timeout / anonym_token.outdated, каскад залипает на 9.
 */
object VkNetworkExcludes {
    private const val TAG = "VkNetworkExcludes"

    private val VK_HOSTS = listOf(
        "api.vk.ru",
        "api.vk.com",
        "login.vk.ru",
        "login.vk.com",
        "id.vk.ru",
        "oauth.vk.ru",
        "oauth.vk.com",
        "stun.vk.com",
        "turn.vk.com",
        "vk.ru",
        "vk.com",
    )

    private val IPV4 = Regex("""\d+\.\d+\.\d+\.\d+""")

    fun resolveExcludeIps(): List<String> {
        val out = linkedSetOf<String>()
        for (host in VK_HOSTS) {
            runCatching {
                InetAddress.getAllByName(host)
            }.onFailure { e ->
                DebugLog.w(TAG, "resolve $host: ${e.message}")
            }.onSuccess { addrs ->
                addrs.mapNotNull { it.hostAddress?.trim() }
                    .filter { it.matches(IPV4) }
                    .forEach { out.add(it) }
            }
        }
        DebugLog.i(TAG, "VK exclude IPs: ${out.size}")
        return out.toList()
    }
}
