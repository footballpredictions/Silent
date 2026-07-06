package com.silent.vpn.data

import com.silent.vpn.util.DebugLog

/** Перед VPN: слоты на сервере, свежие хеши, максимум потоков для libclient (как PC). */
suspend fun SilentRepository.prepareVpnConnectConfig(
    config: VpnConfig,
    fingerprint: String,
): VpnConfig {
    var merged = config

    var hashItems = getSavedHashItems()
    runCatching {
        val hres = getApi().getVpnHashes()
        if (hres.isSuccessful) {
            val items = hres.body()?.toHashItems().orEmpty()
            if (items.isNotEmpty()) {
                saveHashItems(items)
                hashItems = items
            }
        }
        val active = hashItems.activeServerHashes().size
        if (active < HashChannelHelper.MAX_HASHES) {
            runCatching { getApi().requestHashRefresh(ConnectRequest(fingerprint, getApiDeviceType())) }
            val again = getApi().getVpnHashes()
            if (again.isSuccessful) {
                val refreshed = again.body()?.toHashItems().orEmpty()
                if (refreshed.size > hashItems.size) {
                    saveHashItems(refreshed)
                    hashItems = refreshed
                }
            }
        }
    }.onFailure {
        DebugLog.w("PrepareVpnConnect", "hash sync: ${it.message}")
    }

    val boot = getBootstrapHash()?.trim().orEmpty()
    val serverFromItems = hashItems.activeServerHashes().map { it.hash.trim() }.filter { it.isNotBlank() }
    if (serverFromItems.isNotEmpty()) {
        merged = merged.copy(vk_hashes = serverFromItems.take(HashChannelHelper.MAX_HASHES))
    } else {
        merged = merged.copy(
            vk_hashes = merged.vk_hashes
                .filter { it.isNotBlank() && it.trim() != boot }
                .distinct()
                .take(HashChannelHelper.MAX_HASHES),
        )
    }

    runCatching {
        val cfg = getApi().getConfig(fingerprint)
        if (cfg.isSuccessful) {
            val fresh = cfg.body()!!
            val freshServer = fresh.vk_hashes
                .filter { it.isNotBlank() && it.trim() != boot }
                .distinct()
                .take(HashChannelHelper.MAX_HASHES)
            merged = merged.copy(
                device_id = fresh.device_id,
                wg_private_key = fresh.wg_private_key,
                wg_address = fresh.wg_address,
                wg_dns = fresh.wg_dns,
                server_ip = fresh.server_ip,
                server_port = fresh.server_port,
                server_public_key = fresh.server_public_key,
                wdtt_password = fresh.wdtt_password,
                vk_hashes = freshServer.ifEmpty { merged.vk_hashes },
                stream_count = fresh.stream_count,
            )
        }
    }.onFailure {
        DebugLog.w("PrepareVpnConnect", "config refresh: ${it.message}")
    }

    val activeCount = maxOf(
        merged.vk_hashes.size,
        hashItems.activeServerHashes().size,
        1,
    ).coerceAtMost(HashChannelHelper.MAX_HASHES)
    val userWorkers = resolveWorkersForLibclient(activeCount)
    val serverWorkers = merged.stream_count.takeIf { it >= HashChannelHelper.WORKERS_PER_GROUP }
    val workers = if (serverWorkers != null && serverWorkers > userWorkers) {
        HashChannelHelper.workersForLibclient(serverWorkers, activeCount)
    } else {
        userWorkers
    }
    merged = merged.copy(stream_count = workers)
    DebugLog.i(
        "PrepareVpnConnect",
        "n=$workers hashes=${merged.vk_hashes.size} activeHashes=$activeCount",
    )
    return merged
}
