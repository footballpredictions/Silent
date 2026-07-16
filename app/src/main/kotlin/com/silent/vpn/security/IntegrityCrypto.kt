package com.silent.vpn.security

import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest

/**
 * Чистая крипто/сравнительная логика integrity — без Android Context.
 * Используется [AppIntegrity] и юнит-тестами.
 */
object IntegrityCrypto {

    data class Verdict(
        val ok: Boolean,
        val reason: String? = null,
    )

    fun sha256Hex(bytes: ByteArray): String {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(bytes).joinToString("") { b -> "%02x".format(b) }
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

    fun normalizePin(expected: String?): String =
        expected?.trim()?.lowercase().orEmpty()

    /** Пустой pin = проверка выключена (debug / нет keystore на CI). */
    fun pinEnabled(expected: String?): Boolean =
        normalizePin(expected).isNotEmpty()

    fun hashesMatch(actual: String?, expected: String?): Boolean {
        val exp = normalizePin(expected)
        if (exp.isEmpty()) return true
        return actual != null && actual.trim().lowercase() == exp
    }

    fun libHashForAbi(
        abi: String,
        arm64: String,
        arm32: String,
        x86_64: String,
        x86: String,
    ): String =
        when (abi) {
            "arm64-v8a" -> arm64
            "armeabi-v7a" -> arm32
            "x86_64" -> x86_64
            "x86" -> x86
            else -> ""
        }.let { normalizePin(it) }

    /**
     * Release-only вердикт. При [debugBuild]=true всегда OK.
     * Пустые pins пропускаются (не fail).
     */
    fun evaluateReleaseIntegrity(
        debugBuild: Boolean,
        certExpected: String,
        certActual: String?,
        libExpected: String,
        libFileExists: Boolean,
        libActualHash: String?,
    ): Verdict {
        if (debugBuild) return Verdict(ok = true)

        if (pinEnabled(certExpected)) {
            if (!hashesMatch(certActual, certExpected)) {
                return Verdict(
                    ok = false,
                    reason = "Подпись приложения не совпадает с официальной. Установите Silent VPN с официального сайта.",
                )
            }
        }

        if (pinEnabled(libExpected)) {
            if (!libFileExists) {
                return Verdict(
                    ok = false,
                    reason = "Повреждён VPN-модуль (libclient). Переустановите приложение.",
                )
            }
            if (!hashesMatch(libActualHash, libExpected)) {
                return Verdict(
                    ok = false,
                    reason = "VPN-модуль изменён или повреждён. Переустановите приложение с официального сайта.",
                )
            }
        }

        return Verdict(ok = true)
    }
}
