package com.silent.vpn.data

fun VpnHashesResponse.toHashItems(): List<HashItemDto> {
    val fromItems = items.orEmpty().filter { it.hash.isNotBlank() }
    if (fromItems.isNotEmpty()) return fromItems

    val bootHash = bootstrap_hash?.trim().orEmpty()
    return hashes.filter { it.isNotBlank() }.mapIndexed { i, h ->
        val isBootstrap = bootHash.isNotEmpty() && h == bootHash
        HashItemDto(
            hash = h,
            label = if (isBootstrap) "Bootstrap" else "Сервер #${if (bootHash.isNotEmpty()) maxOf(i - 1, 0) else i}",
            source = if (isBootstrap) "bootstrap" else "server",
            slot_index = if (isBootstrap) null else (if (bootHash.isNotEmpty()) maxOf(i - 1, 0) else i),
            is_active = true,
            status = "active",
        )
    }
}

fun List<HashItemDto>.activeServerHashes(): List<HashItemDto> =
    filter { it.source == "server" && it.is_active && it.status == "active" && it.hash.isNotBlank() }
