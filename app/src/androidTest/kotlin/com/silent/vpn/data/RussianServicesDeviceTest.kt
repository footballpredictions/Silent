package com.silent.vpn.data

import android.os.Build
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.vpn.resolveAppTunnelPolicy
import com.silent.vpn.vpn.resolveBootstrapExcludedApps
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Local state only, on the disposable emulator; never uses an owner's account. */
@RunWith(AndroidJUnit4::class)
class RussianServicesDeviceTest {
    private fun context() = InstrumentationRegistry.getInstrumentation().targetContext.also {
        assumeTrue(Build.HARDWARE == "ranchu" || Build.HARDWARE == "goldfish")
    }

    @Test fun priorityRetainsBothListsAndRestoresTheirActiveMode() {
        val context = context()
        val repo = SilentRepository(context)
        RussianServices.setEnabled(context, false)
        repo.saveExcludedApps(setOf(context.packageName), false)
        repo.saveExcludedApps(setOf("com.android.settings"), true)
        repo.saveBypassRoutes("mail.ru", false)
        repo.saveBypassRoutes("example.com", true)
        val before = resolveAppTunnelPolicy(context)
        val bootstrap = resolveBootstrapExcludedApps(context)
        val overlay = resolveAppTunnelPolicy(context, includeAppInTunnel = true)
        RussianServices.setEnabled(context, true)
        try {
            val active = resolveAppTunnelPolicy(context)
            assertFalse(active.whitelist)
            assertEquals(setOf(context.packageName), active.packages)
            assertEquals(bootstrap, resolveBootstrapExcludedApps(context))
            assertEquals(overlay, resolveAppTunnelPolicy(context, includeAppInTunnel = true))
            repo.saveExcludedApps(emptySet(), false)
            repo.saveExceptionsMode(false)
            repo.saveBypassRoutes("changed.com", false)
            repo.saveSitesWhitelist(false)
            assertTrue(repo.isExclusionsWhitelist())
            assertTrue(repo.isSitesWhitelist())
            assertEquals(setOf(context.packageName), repo.getBlacklistPackages())
            assertEquals(setOf("com.android.settings"), repo.getWhitelistPackages())
            assertEquals("mail.ru", repo.getBypassRoutesRaw(false))
            assertEquals("example.com", repo.getBypassRoutesRaw(true))
        } finally { RussianServices.setEnabled(context, false) }
        assertEquals(before, resolveAppTunnelPolicy(context))
        assertEquals("example.com", repo.getBypassRoutesRaw())
    }

    @Test fun invalidPolicyCacheFallsBackWithoutChangingSavedLists() {
        val context = context()
        val prefs = SilentPrefs.open(context)
        val key = "russian_routing_policy_v1"
        val old = prefs.getString(key, null)
        prefs.edit().putString(key, "{\"schema_version\":9}").commit()
        try {
            val policy = RussianServices.config(context)
            assertEquals(1, policy.getInt("schema_version"))
            val bundled = org.json.JSONObject(context.assets.open("russian-services-policy.json").bufferedReader().use { it.readText() })
            assertEquals(bundled.getString("revision"), policy.getString("revision"))
            assertEquals(bundled.getJSONArray("direct_domains").toString(), policy.getJSONArray("direct_domains").toString())
            assertTrue(policy.getJSONArray("vpn_domains").length() > 0)
            assertFalse(policy.getBoolean("enabled"))
        } finally { prefs.edit().putString(key, old).commit() }
    }
}
