package com.silent.vpn.security

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Debug
import com.silent.vpn.BuildConfig
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.DevicePlatform
import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest

/**
 * Release-only защита целостности сборки.
 *
 * Debug / instrumented — всегда OK (не ломает разработку).
 * Release: проверка подписи APK + SHA-256 libclient.so.
 * При провале — блокируем новый VPN connect, не рвём уже поднятый туннель.
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
        val certExpected = BuildConfig.RELEASE_CERT_SHA256.trim().lowercase()
        if (certExpected.isNotEmpty()) {
            val actual = signingCertSha256(context)
            if (actual == null || actual != certExpected) {
                ok = false
                failReason =
                    "Подпись приложения не совпадает с официальной. Установите Silent VPN с официального сайта."
                DebugLog.e("AppIntegrity", "cert mismatch expected=$certExpected actual=$actual")
                return
            }
        }

        val abi = DevicePlatform.primaryAbi()
        val expectedLib = expectedLibclientHash(abi)
        if (expectedLib.isNotEmpty()) {
            val libFile = File(context.applicationInfo.nativeLibraryDir, "libclient.so")
            if (!libFile.exists()) {
                ok = false
                failReason = "Повреждён VPN-модуль (libclient). Переустановите приложение."
                DebugLog.e("AppIntegrity", "libclient missing abi=$abi")
                return
            }
            val actual = sha256Hex(libFile)
            if (actual != expectedLib) {
                ok = false
                failReason = "VPN-модуль изменён или повреждён. Переустановите приложение с официального сайта."
                DebugLog.e("AppIntegrity", "libclient hash mismatch abi=$abi")
                return
            }
        }

        if (isDebuggerAttached()) {
            // Soft: только лог — не блокируем (иначе ломают легитимный attach в редких кейсах).
            DebugLog.w("AppIntegrity", "debugger attached on release build")
        }

        ok = true
        failReason = null
        DebugLog.i("AppIntegrity", "release integrity OK abi=$abi")
    }

    private fun expectedLibclientHash(abi: String): String =
        when (abi) {
            "arm64-v8a" -> BuildConfig.LIBCLIENT_SHA256_ARM64
            "armeabi-v7a" -> BuildConfig.LIBCLIENT_SHA256_ARM32
            "x86_64" -> BuildConfig.LIBCLIENT_SHA256_X86_64
            "x86" -> BuildConfig.LIBCLIENT_SHA256_X86
            else -> ""
        }.trim().lowercase()

    private fun signingCertSha256(context: Context): String? {
        return try {
            val pm = context.packageManager
            val pkg = context.packageName
            val signatures = if (Build.VERSION.SDK_INT >= 28) {
                val info = pm.getPackageInfo(pkg, PackageManager.GET_SIGNING_CERTIFICATES)
                val si = info.signingInfo ?: return null
                // Текущие подписи APK (не history ротации)
                si.apkContentsSigners
            } else {
                @Suppress("DEPRECATION")
                pm.getPackageInfo(pkg, PackageManager.GET_SIGNATURES).signatures
            }
            val sig = signatures?.firstOrNull() ?: return null
            sha256Hex(sig.toByteArray())
        } catch (e: Exception) {
            DebugLog.e("AppIntegrity", "signingCertSha256: ${e.message}")
            null
        }
    }

    fun sha256Hex(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buf = ByteArray(8192)
            while (true) {
                val n = input.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { b -> "%02x".format(b) }
    }

    private fun sha256Hex(bytes: ByteArray): String {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(bytes).joinToString("") { b -> "%02x".format(b) }
    }
}
