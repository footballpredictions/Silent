package com.silent.vpn.data

/** Серверные хеши для UI и `-n` (bootstrap только для входа, не показываем). */
fun VpnHashesResponse.toHashItems(): List<HashItemDto> {
    val fromItems = items.orEmpty()
        .filter { it.hash.isNotBlank() && it.source != "bootstrap" }
    if (fromItems.isNotEmpty()) return fromItems

    val bootHash = bootstrap_hash?.trim().orEmpty()
    return hashes.filter { it.isNotBlank() && it != bootHash }.mapIndexed { i, h ->
        HashItemDto(
            hash = h,
            label = "Сервер #$i",
            source = "server",
            slot_index = i,
            is_active = true,
            status = "active",
        )
    }
}

fun List<HashItemDto>.activeServerHashes(): List<HashItemDto> =
    filter { it.source != "bootstrap" && it.is_active && it.status == "active" && it.hash.isNotBlank() }

fun List<HashItemDto>.activeServerHashCount(): Int =
    activeServerHashes().size.coerceIn(1, HashChannelHelper.MAX_HASHES)

fun List<String>.serverHashesExcludingBootstrap(bootstrap: String?): List<String> {
    val boot = bootstrap?.trim().orEmpty()
    return filter { it.isNotBlank() && it != boot }
}
