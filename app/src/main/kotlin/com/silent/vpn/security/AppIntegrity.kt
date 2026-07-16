package com.silent.vpn.security

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Debug
import com.silent.vpn.BuildConfig
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.DevicePlatform
import java.io.File

/**
 * Release-only защита целостности сборки.
 *
 * Debug / instrumented — всегда OK (не ломает разработку).
 * Release: проверка подписи APK + SHA-256 libclient.so.
 * При провале — блокируем новый VPN connect, не рвём уже поднятый туннель.
 *
 * Чистая логика сравнения — [IntegrityCrypto] (покрыта юнит-тестами).
 */
object AppIntegrity {

    @Volatile
    private var checked = false

    @Volatile
    private var ok: Boolean = true

    @Volatile
    private var failReason: String? = null

    fun isOk(): Boolean {
        if (BuildConfig.DEBUG) return true
        return ok
    }

    fun failMessage(): String =
        failReason
            ?: "Сборка повреждена или изменена. Установите Silent VPN с официального сайта."

    /** Фоновая проверка при старте приложения. */
    fun verifyAsync(context: Context) {
        if (BuildConfig.DEBUG) {
            checked = true
            ok = true
            return
        }
        Thread {
            runCatching { verifyBlocking(context.applicationContext) }
                .onFailure { e ->
                    ok = false
                    failReason = "Ошибка проверки сборки: ${e.message}"
                    DebugLog.e("AppIntegrity", failReason!!)
                }
            checked = true
        }.start()
    }

    /** Синхронно перед стартом libclient (release). */
    fun ensureOkForVpn(context: Context): Boolean {
        if (BuildConfig.DEBUG) return true
        if (!checked) {
            runCatching { verifyBlocking(context.applicationContext) }
            checked = true
        }
        return ok
    }

    /** Soft-сигнал отладчика (не блокирует VPN сам по себе). */
    fun isDebuggerAttached(): Boolean =
        Debug.isDebuggerConnected() || Debug.waitingForDebugger()

    private fun verifyBlocking(context: Context) {
        val certExpected = BuildConfig.RELEASE_CERT_SHA256
        val certActual = if (IntegrityCrypto.pinEnabled(certExpected)) {
            signingCertSha256(context)
        } else {
            null
        }

        val abi = DevicePlatform.primaryAbi()
        val libExpected = IntegrityCrypto.libHashForAbi(
            abi = abi,
            arm64 = BuildConfig.LIBCLIENT_SHA256_ARM64,
            arm32 = BuildConfig.LIBCLIENT_SHA256_ARM32,
            x86_64 = BuildConfig.LIBCLIENT_SHA256_X86_64,
            x86 = BuildConfig.LIBCLIENT_SHA256_X86,
        )
        val libFile = File(context.applicationInfo.nativeLibraryDir, "libclient.so")
        val libExists = libFile.exists()
        val libActual = if (IntegrityCrypto.pinEnabled(libExpected) && libExists) {
            IntegrityCrypto.sha256Hex(libFile)
        } else {
            null
        }

        val verdict = IntegrityCrypto.evaluateReleaseIntegrity(
            debugBuild = false,
            certExpected = certExpected,
            certActual = certActual,
            libExpected = libExpected,
            libFileExists = libExists,
            libActualHash = libActual,
        )

        if (!verdict.ok) {
            ok = false
            failReason = verdict.reason
            DebugLog.e("AppIntegrity", "fail abi=$abi reason=${verdict.reason}")
            return
        }

        if (isDebuggerAttached()) {
            DebugLog.w("AppIntegrity", "debugger attached on release build")
        }

        ok = true
        failReason = null
        DebugLog.i("AppIntegrity", "release integrity OK abi=$abi")
    }

    private fun signingCertSha256(context: Context): String? {
        return try {
            val pm = context.packageManager
            val pkg = context.packageName
            val signatures = if (Build.VERSION.SDK_INT >= 28) {
                val info = pm.getPackageInfo(pkg, PackageManager.GET_SIGNING_CERTIFICATES)
                val si = info.signingInfo ?: return null
                si.apkContentsSigners
            } else {
                @Suppress("DEPRECATION")
                pm.getPackageInfo(pkg, PackageManager.GET_SIGNATURES).signatures
            }
            val sig = signatures?.firstOrNull() ?: return null
            IntegrityCrypto.sha256Hex(sig.toByteArray())
        } catch (e: Exception) {
            DebugLog.e("AppIntegrity", "signingCertSha256: ${e.message}")
            null
        }
    }

    /** Для совместимости / тестов файлов. */
    fun sha256Hex(file: File): String = IntegrityCrypto.sha256Hex(file)
}
