package com.silent.vpn.data

/** Серверные хеши для UI и `-n` (bootstrap только для входа, не показываем). */
fun VpnHashesResponse.toHashItems(): List<HashItemDto> {
    val fromItems = items.orEmpty()
        .filter { it.hash.isNotBlank() && it.source != "bootstrap" }
        .mapIndexed { i, item -> item.sanitize(i) }
    if (fromItems.isNotEmpty()) return fromItems

    val bootHash = bootstrap_hash?.trim().orEmpty()
    return hashes.filter { it.isNotBlank() && it != bootHash }.mapIndexed { i, h ->
        HashItemDto(
            hash = h.trim(),
            label = "Сервер #${i + 1}",
            source = "server",
            slot_index = i,
            is_active = true,
            status = "active",
        )
    }
}

/** Защита от null/пустых полей после Gson (иначе NPE в UI «Хеши»). */
fun HashItemDto.sanitize(index: Int = 0): HashItemDto {
    val slot = slot_index ?: index
    return copy(
        hash = hash.trim(),
        label = label.takeIf { it.isNotBlank() } ?: "Сервер #${slot + 1}",
        source = source.takeIf { it.isNotBlank() } ?: "server",
        status = status.takeIf { it.isNotBlank() } ?: if (is_active) "active" else "expired",
    )
}

fun List<HashItemDto>.sanitized(): List<HashItemDto> =
    mapIndexed { i, item -> item.sanitize(i) }

fun List<HashItemDto>.activeServerHashes(): List<HashItemDto> =
    filter { it.source != "bootstrap" && it.is_active && it.status == "active" && it.hash.isNotBlank() }

fun List<HashItemDto>.activeServerHashCount(): Int =
    activeServerHashes().size.coerceAtMost(HashChannelHelper.MAX_HASHES)

fun List<String>.serverHashesExcludingBootstrap(bootstrap: String?): List<String> {
    val boot = bootstrap?.trim().orEmpty()
    return filter { it.isNotBlank() && it != boot }
}
