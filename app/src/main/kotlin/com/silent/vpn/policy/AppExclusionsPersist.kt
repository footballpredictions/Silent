package com.silent.vpn.policy

/**
 * Два независимых списка исключений + режим.
 * Смена режима не очищает другой список. Старый один массив мигрирует в активный режим.
 */
object AppExclusionsPersist {

    data class State(
        val whitelist: Boolean,
        val blacklistAppIds: Set<String>,
        val whitelistAppIds: Set<String>,
    ) {
        val activeIds: Set<String>
            get() = if (whitelist) whitelistAppIds else blacklistAppIds

        val appBypassMode: String
            get() = if (whitelist) "whitelist" else "blacklist"
    }

    data class TunnelIntent(
        val whitelist: Boolean,
        val userPackages: Set<String>,
    )

    fun hydrate(
        selectedIds: Set<String>,
        whitelist: Boolean,
        blacklistAppIds: Set<String>? = null,
        whitelistAppIds: Set<String>? = null,
    ): State {
        if (blacklistAppIds != null || whitelistAppIds != null) {
            return State(
                whitelist = whitelist,
                blacklistAppIds = blacklistAppIds ?: emptySet(),
                whitelistAppIds = whitelistAppIds ?: emptySet(),
            )
        }
        return if (whitelist) {
            State(whitelist = true, blacklistAppIds = emptySet(), whitelistAppIds = selectedIds)
        } else {
            State(whitelist = false, blacklistAppIds = selectedIds, whitelistAppIds = emptySet())
        }
    }

    fun switchMode(state: State, toWhitelist: Boolean): State =
        state.copy(whitelist = toWhitelist)

    fun setActive(state: State, ids: Set<String>): State =
        if (state.whitelist) state.copy(whitelistAppIds = ids)
        else state.copy(blacklistAppIds = ids)

    /**
     * Пустой БС = весь трафик в VPN (как пустой ЧС), а не «все приложения мимо».
     */
    fun tunnelIntent(state: State): TunnelIntent {
        if (state.whitelist) {
            if (state.whitelistAppIds.isEmpty()) {
                return TunnelIntent(whitelist = false, userPackages = emptySet())
            }
            return TunnelIntent(whitelist = true, userPackages = state.whitelistAppIds)
        }
        return TunnelIntent(whitelist = false, userPackages = state.blacklistAppIds)
    }
}
