package com.silent.vpn.policy

/** Splash/тумблер: сначала публичный API (Улей, затем соты). Hive WG bootstrap — если API молчит. */
object ConnectConfigFetchPolicy {
    fun skipPublicFailover(onMobile: Boolean, forLaunch: Boolean): Boolean {
        // Раньше splash (`forLaunch`) и LTE сразу шли в ephemeral на Улей :56000.
        // При блоке 443/WG анимация не поднимала временный интернет и не видела подписку.
        return false
    }

    /**
     * Слоты, которые splash обязан запросить у API.
     * Временный VPN при этом не обязателен: если белые списки выключены, конфиг идёт
     * по открытому интернету. Уже лежащий кеш запрос не отменяет — иначе слоты 2–4
     * остаются старыми, а Сервер 4 не запрашивается вовсе.
     */
    fun launchConfigSlots(alreadyCached: Collection<String> = emptyList()): List<String> {
        val slots = VpnServerListPolicy.staticKeys()
        return if (alreadyCached.isEmpty()) slots else slots
    }

    /** Удачный WG-конфиг пишем всегда. Старый кеш и чужой IP не оставляем вместо нового ответа. */
    fun shouldPersistFetchedConfig(connectable: Boolean, ipMatchesSlot: Boolean): Boolean {
        if (!connectable) return false
        return ipMatchesSlot || !ipMatchesSlot
    }

    /** Туннель поднялся уже после таймаута ожидания — один запрос до того, как splash его погасит. */
    fun fetchConfigsBeforeStoppingBootstrap(tunnelReady: Boolean, configsAlreadySaved: Boolean): Boolean =
        tunnelReady && !configsAlreadySaved
}
