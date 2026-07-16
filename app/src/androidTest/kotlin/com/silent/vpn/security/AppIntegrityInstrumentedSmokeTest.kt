package com.silent.vpn.security

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.silent.vpn.BuildConfig
import com.silent.vpn.util.DevicePlatform
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Device smoke для anti-tamper.
 *
 * Debug/instrumented: [AppIntegrity] всегда пропускает (не ломает QA).
 * Полная проверка пинов cert/libclient — только на release APK + keystore
 * (см. юнит-тесты [IntegrityCryptoTest]).
 */
@RunWith(AndroidJUnit4::class)
class AppIntegrityInstrumentedSmokeTest {

    @Test
    fun debugBuildIntegrityAlwaysOk() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertTrue(BuildConfig.DEBUG)
        assertTrue(AppIntegrity.isOk())
        assertTrue(AppIntegrity.ensureOkForVpn(context))
    }

    @Test
    fun libclientPresentAndHashableOnDevice() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val lib = File(context.applicationInfo.nativeLibraryDir, "libclient.so")
        assertTrue(
            "libclient.so must be packaged for ABI ${DevicePlatform.primaryAbi()}",
            lib.exists() && lib.length() > 0L,
        )
        val hash = IntegrityCrypto.sha256Hex(lib)
        assertEquals(64, hash.length)
        assertTrue(hash.all { it in '0'..'9' || it in 'a'..'f' })
        // Повторный хеш стабилен
        assertEquals(hash, IntegrityCrypto.sha256Hex(lib))
    }

    @Test
    fun evaluateReleaseIntegrityDetectsTamperOnDevice() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val lib = File(context.applicationInfo.nativeLibraryDir, "libclient.so")
        require(lib.exists())
        val real = IntegrityCrypto.sha256Hex(lib)
        val bad = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "",
            certActual = null,
            libExpected = "a".repeat(64),
            libFileExists = true,
            libActualHash = real,
        )
        assertTrue(!bad.ok)
        val good = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = "",
            certActual = null,
            libExpected = real,
            libFileExists = true,
            libActualHash = real,
        )
        assertTrue(good.ok)
    }
}
