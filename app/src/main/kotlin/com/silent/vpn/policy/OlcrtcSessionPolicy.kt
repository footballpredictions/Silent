package com.silent.vpn.policy

/**
 * Чистые правила olcrtc2-сессии: кеш Telemost↔WB, heartbeat leave, accept config.
 * Без Android — покрывается юнит-тестами.
 */
object OlcrtcSessionPolicy {

    const val PROVIDER_TELEMOST = "telemost"
    const val PROVIDER_WBSTREAM = "wbstream"

    fun normalizeProvider(raw: String?): String = when (raw?.trim()?.lowercase()) {
        PROVIDER_WBSTREAM -> PROVIDER_WBSTREAM
        PROVIDER_TELEMOST -> PROVIDER_TELEMOST
        else -> PROVIDER_TELEMOST
    }

    fun cacheKey(provider: String): String =
        "olcrtc_config_cache_v16_${normalizeProvider(provider)}"

    /** Смена prefs-провайдера не должна трогать чужой слот кеша. */
    fun shouldClearCacheOnProviderSwitch(): Boolean = false

    /**
     * Cancel/restart heartbeat job не должен вызывать leave —
     * иначе живой VPN рвёт комнату и чистит кеш («нет сессии» / зелёный труп).
     */
    fun shouldLeaveOnHeartbeatCancel(): Boolean = false

    /** Второй start при уже активном loop — no-op. */
    fun shouldStartHeartbeat(alreadyActive: Boolean): Boolean = !alreadyActive

    /**
     * Leave / fail / heartbeat привязаны к снимку сессии, не к prefs после Apply.
     */
    fun resolveSessionProvider(
        sessionProvider: String?,
        prefsProvider: String,
    ): String = normalizeProvider(sessionProvider ?: prefsProvider)

    fun resolveLeaveTarget(
        sessionProvider: String?,
        sessionRoomDbId: String?,
        prefsProvider: String,
    ): LeaveTarget {
        val provider = resolveSessionProvider(sessionProvider, prefsProvider)
        val roomDbId = sessionRoomDbId?.trim()?.takeIf { it.isNotEmpty() }
        return LeaveTarget(provider = provider, roomDbId = roomDbId)
    }

    /** При Apply смены канала при живом туннеле — сначала leave+stop старого. */
    fun shouldStopVpnBeforeProviderApply(
        pendingProvider: String?,
        currentProvider: String,
        vpnOrTunnelRunning: Boolean,
    ): Boolean {
        if (!vpnOrTunnelRunning) return false
        val pending = pendingProvider?.let { normalizeProvider(it) } ?: return false
        return pending != normalizeProvider(currentProvider)
    }

    /**
     * Accept только живой assign: enabled + crypto + room в слоте.
     * denied/пусто → null (кеш не трогаем, fetch падает на fallback).
     */
    fun shouldAcceptAssign(
        enabled: Boolean,
        cryptoKeyLen: Int,
        providerEnabled: Boolean?,
        room: String?,
        denied: Boolean?,
        poolDenied: Boolean?,
    ): Boolean {
        if (!enabled || cryptoKeyLen != 64) return false
        if (denied == true) return false
        if (providerEnabled == false) return false
        val r = room?.trim().orEmpty()
        if (r.isEmpty()) return false
        if (poolDenied == true && r.isEmpty()) return false
        return true
    }

    /** Leave не чистит кеш (dual-cache 1.0.160). Wipe только на failure. */
    fun cacheProvidersToClearOnLeave(sessionProvider: String): Set<String> = emptySet()

    fun cacheProvidersToClearOnFailure(sessionProvider: String): Set<String> =
        setOf(normalizeProvider(sessionProvider))

    /**
     * Apply: есть слот → cache-only (как 1.0.160). Сервер leave ≠ teardown.
     * Revalidate только если selected пуст.
     */
    fun shouldRevalidateSelectedOnApply(selectedRoomCached: Boolean): Boolean = !selectedRoomCached

    /**
     * Apply — только кеш. Fetch слотов: login + живой VK-туннель, не диалог «ждём конфиг».
     */
    fun providersToFetchOnApply(
        @Suppress("UNUSED_PARAMETER") tmRoomOk: Boolean,
        @Suppress("UNUSED_PARAMETER") wbRoomOk: Boolean,
    ): List<String> = emptyList()

    /** Тумблер выкл., native/hev ещё жив — hardReset, иначе WB накладывается на TM/VK. */
    fun shouldHardResetLeftoverNative(
        vpnServiceRunning: Boolean,
        nativeRunning: Boolean,
        tunnelReady: Boolean,
    ): Boolean = nativeRunning || tunnelReady

    /**
     * code=1 на первой попытке часто stale onDestroy, не мёртвая комната.
     * Wipe слота → «нет конфига» на WB→TM.
     */
    fun shouldWipeCacheOnEarlyFail(detail: String, attempt: Int): Boolean {
        val d = detail.lowercase()
        if (
            d.contains("гост") || d.contains("auth.token") || d.contains("join room") ||
            d.contains("wb join 404") || d.contains("not found")
        ) {
            return true
        }
        if (attempt == 0 && (d.contains("code=1") || d.contains("вышел"))) return false
        return true
    }

    /** Уход с olcrtc на VK: снести native/hev даже если VpnService уже «выкл». */
    fun shouldHardResetOlcrtcOnFamilyLeave(fromFamily: String, toFamily: String): Boolean {
        fun isOlc(raw: String): Boolean {
            val f = raw.trim().lowercase()
            return f == "olcrtc" || f == "olcrtc2"
        }
        return isOlc(fromFamily) && !isOlc(toFamily)
    }

    /** Connect: preferCache если слот есть (комната в пуле жива). */
    fun shouldPreferCacheOnConnect(slotDirtyAfterLeave: Boolean, hasCachedRoom: Boolean): Boolean =
        hasCachedRoom

    /** Prefetch: не force выбранный, если слот уже есть — иначе wipe sticky на сервере. */
    fun shouldForcePrefetch(provider: String, selectedProvider: String): Boolean = false

    fun prefetchOk(
        force: Boolean,
        hadCacheBefore: Boolean,
        fetchedRoomNonBlank: Boolean,
        hasCacheAfter: Boolean,
    ): Boolean {
        if (fetchedRoomNonBlank) return true
        if (!force && hadCacheBefore) return true
        return hasCacheAfter
    }

    /**
     * В ключ кеша пишем только запрошенный провайдер.
     * Ответ с двумя слотами не должен затирать соседа.
     */
    fun isolateProviderKeysForCache(
        requestedProvider: String?,
        incomingKeys: Collection<String>,
    ): Set<String> {
        val want = requestedProvider?.let { normalizeProvider(it) }
        val incoming = incomingKeys.map { normalizeProvider(it) }.toSet()
        if (want != null) return incoming.filter { it == want }.toSet()
        return incoming.filter { it == PROVIDER_TELEMOST || it == PROVIDER_WBSTREAM }.toSet()
    }

    data class LeaveTarget(
        val provider: String,
        val roomDbId: String?,
    )

    /**
     * In-memory multi-slot store для юнит-тестов (зеркало v14 prefs).
     */
    class SlotStore {
        private val slots = linkedMapOf<String, Slot>()

        data class Slot(
            val provider: String,
            val room: String,
            val roomDbId: String,
            val cryptoKey: String,
            val enabled: Boolean = true,
        )

        fun put(slot: Slot) {
            if (!shouldAcceptAssign(
                    enabled = slot.enabled,
                    cryptoKeyLen = slot.cryptoKey.length,
                    providerEnabled = true,
                    room = slot.room,
                    denied = false,
                    poolDenied = false,
                )
            ) {
                return
            }
            slots[normalizeProvider(slot.provider)] = slot.copy(
                provider = normalizeProvider(slot.provider),
            )
        }

        fun get(provider: String): Slot? = slots[normalizeProvider(provider)]

        fun clear(provider: String) {
            slots.remove(normalizeProvider(provider))
        }

        fun clearAll() = slots.clear()

        fun providers(): Set<String> = slots.keys.toSet()

        /** Симуляция Apply: смена selected без wipe чужого слота. */
        fun applyProviderSwitch(from: String, to: String): SwitchResult {
            require(!shouldClearCacheOnProviderSwitch())
            val fromSlot = get(from)
            val toSlot = get(to)
            return SwitchResult(
                selected = normalizeProvider(to),
                fromStillCached = fromSlot != null,
                toCached = toSlot != null,
                missingSession = toSlot == null,
            )
        }

        /**
         * Симуляция бага: leave по prefs после Apply при живой старой сессии.
         * Правильно — leave по sessionProvider.
         */
        fun leave(
            sessionProvider: String?,
            prefsProvider: String,
        ): LeaveResult {
            val target = resolveLeaveTarget(sessionProvider, null, prefsProvider)
            val before = providers()
            for (p in cacheProvidersToClearOnLeave(target.provider)) {
                clear(p)
            }
            return LeaveResult(
                cleared = target.provider,
                remaining = providers(),
                wipedUnrelated = before.any {
                    it != target.provider && it !in providers()
                },
            )
        }
    }

    data class SwitchResult(
        val selected: String,
        val fromStillCached: Boolean,
        val toCached: Boolean,
        val missingSession: Boolean,
    )

    data class LeaveResult(
        val cleared: String,
        val remaining: Set<String>,
        val wipedUnrelated: Boolean,
    )
}
