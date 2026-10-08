package com.silent.vpn.data

import android.content.SharedPreferences

/** Separate site lists; the legacy key mirrors only the active list for VPN readers. */
object SiteExclusionsStore {
    const val ACTIVE_RULES_KEY = "bypass_routes"
    const val MODE_KEY = "sites_whitelist"
    private const val BLACKLIST_KEY = "sites_blacklist_rules"
    private const val WHITELIST_KEY = "sites_whitelist_rules"

    data class State(val whitelist: Boolean, val blacklistRules: String, val whitelistRules: String) {
        val activeRules: String get() = rulesFor(whitelist)
        fun rulesFor(mode: Boolean): String = if (mode) whitelistRules else blacklistRules
    }

    @Synchronized
    fun load(prefs: SharedPreferences): State {
        val mode = prefs.getBoolean(MODE_KEY, false)
        val dual = prefs.contains(BLACKLIST_KEY) || prefs.contains(WHITELIST_KEY)
        val legacy = prefs.getString(ACTIVE_RULES_KEY, "").orEmpty().trim()
        val state = State(
            mode,
            if (dual) prefs.getString(BLACKLIST_KEY, "").orEmpty() else if (mode) "" else legacy,
            if (dual) prefs.getString(WHITELIST_KEY, "").orEmpty() else if (mode) legacy else "",
        )
        if (!dual) persist(prefs, state)
        return state
    }

    @Synchronized
    fun save(prefs: SharedPreferences, raw: String, whitelist: Boolean): State {
        val current = load(prefs)
        val next = if (whitelist) current.copy(whitelist = true, whitelistRules = raw.trim())
        else current.copy(whitelist = false, blacklistRules = raw.trim())
        persist(prefs, next)
        return next
    }

    @Synchronized
    fun switchMode(prefs: SharedPreferences, whitelist: Boolean): State {
        val next = load(prefs).copy(whitelist = whitelist)
        persist(prefs, next)
        return next
    }

    private fun persist(prefs: SharedPreferences, state: State) {
        // Commit all fields together before reloadWireGuard reads the legacy mirror.
        check(prefs.edit()
            .putString(BLACKLIST_KEY, state.blacklistRules)
            .putString(WHITELIST_KEY, state.whitelistRules)
            .putBoolean(MODE_KEY, state.whitelist)
            .putString(ACTIVE_RULES_KEY, state.activeRules)
            .commit()) { "Не удалось сохранить списки сайтов" }
    }
}
