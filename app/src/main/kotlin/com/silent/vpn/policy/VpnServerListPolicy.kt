package com.silent.vpn.policy

import com.silent.vpn.data.VpnServerInfo

/**
 * Слоты 1–4 рисуются сразу, без ожидания API. Сервер 4 в 1.0.165+ статичен
 * («для ИИ»). Ответ API только подставляет IP/онлайн и чужие будущие слоты.
 */
object VpnServerListPolicy {
    const val AI_SLOT = "server4"
    const val AI_TITLE = "Сервер 4 для ИИ"
    private val STATIC_KEYS = listOf("server1", "server2", "server3", AI_SLOT)

    fun staticList(): List<VpnServerInfo> = STATIC_KEYS.map { key ->
        VpnServerInfo(
            key = key,
            title = if (key == AI_SLOT) AI_TITLE else slotTitle(key),
        )
    }

    fun displayList(fromApi: List<VpnServerInfo>?): List<VpnServerInfo> {
        val api = fromApi.orEmpty()
        if (api.isEmpty()) return staticList()
        val byKey = api.associateBy { normalize(it.key) }
        val merged = staticList().map { stub ->
            val known = byKey[stub.key] ?: return@map stub
            val title = known.title.trim().ifBlank { stub.title }.let { raw ->
                if (stub.key == AI_SLOT && (raw.isBlank() || raw == slotTitle(AI_SLOT))) AI_TITLE else raw
            }
            known.copy(key = stub.key, title = title)
        }
        val extras = api.filter { normalize(it.key) !in STATIC_KEYS }
        return merged + extras
    }

    fun slotTitle(slot: String): String {
        val n = slot.removePrefix("server")
        return if (n.isNotBlank() && n.all { it.isDigit() }) "Сервер $n" else slot
    }

    private fun normalize(key: String): String = key.trim().lowercase()
}
