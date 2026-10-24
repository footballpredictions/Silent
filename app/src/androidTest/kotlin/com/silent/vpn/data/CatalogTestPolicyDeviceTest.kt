package com.silent.vpn.data

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.BuildConfig
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CatalogTestPolicyDeviceTest {
    @Test fun enabledRussianModeExcludesInstalledMaxAtApplicationLevel() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue(BuildConfig.WHITELIST_CATALOG_TEST && context.packageName == "com.silent.vpn.catalogtest")
        assumeTrue(RussianServices.enabled(context))
        assumeTrue(runCatching { context.packageManager.getPackageInfo("ru.oneme.app", 0) }.isSuccess)
        val policy = com.silent.vpn.vpn.resolveAppTunnelPolicy(context)
        assertTrue("MAX UID must not enter the Android VPN", "ru.oneme.app" in policy.packages)
    }

    @Test fun liveEncryptedRelayReturnsOnlyCatalogProfile() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue(BuildConfig.WHITELIST_CATALOG_TEST && context.packageName == "com.silent.vpn.catalogtest")
        assumeTrue(InstrumentationRegistry.getArguments().getString("catalogLiveRelay") == "true")
        val download = RussianServices::class.java.getDeclaredMethod("downloadPolicy").apply { isAccessible = true }
        val policy = download.invoke(RussianServices) as? JSONObject
        assertNotNull("Live encrypted relay did not return a valid test profile", policy)
        assertEquals("catalog-test", policy!!.getString("profile"))
        assertTrue(policy.getJSONArray("direct_exact_domains").length() > 0)
        assertTrue(policy.getJSONArray("direct_domains").length() > 0)
        assertEquals("not_measured", policy.getString("reachability"))
    }

    @Test fun isolatedProfileUsesTypedFallbackAndRejectsProductionCache() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assumeTrue(BuildConfig.WHITELIST_CATALOG_TEST && context.packageName == "com.silent.vpn.catalogtest")
        val prefs = SilentPrefs.open(context)
        val key = "catalog_test_routing_policy_v1"
        val previous = prefs.getString(key, null)
        try {
            prefs.edit().remove(key).commit()
            val fallback = RussianServices.config(context)
            assertEquals("catalog-test", fallback.getString("profile"))
            assertTrue(fallback.getJSONArray("direct_exact_domains").length() > 0)
            assertTrue(fallback.getJSONArray("direct_domains").length() > 0)
            val production = context.assets.open("russian-services-policy.json").bufferedReader().use { it.readText() }
            prefs.edit().putString(key, production).commit()
            assertEquals(fallback.getString("revision"), RussianServices.config(context).getString("revision"))
            val invalid = JSONObject(fallback.toString()).put("direct_exact_domains", "invalid")
            prefs.edit().putString(key, invalid.toString()).commit()
            assertEquals(fallback.getString("revision"), RussianServices.config(context).getString("revision"))
        } finally {
            prefs.edit().putString(key, previous).commit()
        }
    }
}
