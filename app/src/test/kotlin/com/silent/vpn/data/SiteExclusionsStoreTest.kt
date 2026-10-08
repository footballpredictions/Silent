package com.silent.vpn.data

import android.content.SharedPreferences
import java.lang.reflect.Proxy
import org.junit.Assert.*
import org.junit.Test

class SiteExclusionsStoreTest {
    private fun preferences(): SharedPreferences {
        val data = mutableMapOf<String, Any?>()
        return Proxy.newProxyInstance(SharedPreferences::class.java.classLoader, arrayOf(SharedPreferences::class.java)) { _, method, args ->
            when (method.name) {
                "getString", "getBoolean" -> if (data.containsKey(args[0])) data[args[0]] else args[1]
                "contains" -> data.containsKey(args[0])
                "edit" -> {
                    val pending = mutableMapOf<String, Any?>()
                    lateinit var editor: SharedPreferences.Editor
                    editor = Proxy.newProxyInstance(SharedPreferences.Editor::class.java.classLoader, arrayOf(SharedPreferences.Editor::class.java)) { _, operation, values ->
                        when (operation.name) {
                            "putString", "putBoolean" -> { pending[values[0] as String] = values[1]; editor }
                            "commit" -> { data.putAll(pending); true }
                            else -> error("Unexpected editor call ${operation.name}")
                        }
                    } as SharedPreferences.Editor
                    editor
                }
                else -> error("Unexpected preferences call ${method.name}")
            }
        } as SharedPreferences
    }

    @Test fun legacyListMigratesOnlyIntoItsActiveMode() {
        for (mode in listOf(false, true)) {
            val prefs = preferences()
            prefs.edit().putBoolean(SiteExclusionsStore.MODE_KEY, mode)
                .putString(SiteExclusionsStore.ACTIVE_RULES_KEY, "youtube.com\n2ip.io").commit()
            val state = SiteExclusionsStore.load(prefs)
            assertEquals("youtube.com\n2ip.io", state.rulesFor(mode))
            assertEquals("", state.rulesFor(!mode))
            assertEquals("", SiteExclusionsStore.switchMode(prefs, !mode).activeRules)
            assertEquals("youtube.com\n2ip.io", SiteExclusionsStore.switchMode(prefs, mode).activeRules)
        }
    }

    @Test fun editingClearingAndReloadingKeepTheTwoListsIndependent() {
        val prefs = preferences()
        SiteExclusionsStore.save(prefs, "mail.ru", false)
        SiteExclusionsStore.switchMode(prefs, true)
        SiteExclusionsStore.save(prefs, "youtube.com\n2ip.io", true)
        assertEquals("mail.ru", SiteExclusionsStore.switchMode(prefs, false).activeRules)
        SiteExclusionsStore.save(prefs, "", false)
        repeat(5) {
            assertEquals("youtube.com\n2ip.io", SiteExclusionsStore.switchMode(prefs, true).activeRules)
            assertEquals("", SiteExclusionsStore.switchMode(prefs, false).activeRules)
        }
        val state = SiteExclusionsStore.load(prefs)
        assertFalse(state.whitelist)
        assertEquals("", state.blacklistRules)
        assertEquals("youtube.com\n2ip.io", state.whitelistRules)
        assertEquals(state.activeRules, prefs.getString(SiteExclusionsStore.ACTIVE_RULES_KEY, null))
        SiteExclusionsStore.switchMode(prefs, true)
        assertEquals("youtube.com\n2ip.io", prefs.getString(SiteExclusionsStore.ACTIVE_RULES_KEY, null))
    }
}
