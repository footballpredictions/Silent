package com.silent.vpn.policy

import com.google.gson.JsonParser

/**
 * OTA discovery that survives hive IP changes.
 * Landing already publishes [RELEASES_JSON_URL]; in-app check used to ask
 * `/api/updates/check` on the baked nip.io and died when that IP moved.
 */
object OtaGithubDiscovery {
    const val RELEASES_JSON_URL = "https://silentvpn3.github.io/releases.json"
    const val FETCH_TIMEOUT_MS = 8_000L

    fun landingKey(platform: String): String = when (platform.trim().lowercase()) {
        "android_tv", "tv" -> "android"
        "macos", "darwin" -> "mac"
        "windows", "win32" -> "pc"
        else -> platform.trim().lowercase()
    }

    sealed class Result {
        data class Available(
            val version: String,
            val filename: String,
            val size: Long,
            val downloadUrl: String,
        ) : Result()

        data class Current(val version: String) : Result()
        data object Unreadable : Result()
    }

    fun parse(json: String?, platform: String, currentVersion: String): Result {
        val release = release(json, platform) ?: return Result.Unreadable
        return if (isNewer(release.version, currentVersion)) release else Result.Current(release.version)
    }

    private val apkAssetUrl = Regex("""https://github\.com/silentvpn3/silentvpn3\.github\.io/releases/download/[^/?#]+/[^/?#]+\.apk""")

    fun latestAndroidApk(json: String?): String? =
        release(json, "android")?.downloadUrl?.takeIf(apkAssetUrl::matches)

    private fun release(json: String?, platform: String): Result.Available? = runCatching {
        val row = JsonParser.parseString(json ?: return null).asJsonObject
            .getAsJsonObject(landingKey(platform)) ?: return null
        val latest = row.get("version")?.asString?.trim().orEmpty()
        val filename = row.get("filename")?.asString?.trim().orEmpty()
        val url = row.get("download_url")?.asString?.trim().orEmpty()
        if (latest.isEmpty() || filename.isEmpty() || !url.startsWith("http")) {
            return null
        }
        Result.Available(
            version = latest,
            filename = filename,
            size = row.get("size")?.asLong ?: 0L,
            downloadUrl = url,
        )
    }.getOrNull()

    fun isNewer(latest: String, current: String): Boolean {
        val a = parseVersion(latest)
        val b = parseVersion(current)
        val n = maxOf(a.size, b.size)
        for (i in 0 until n) {
            val da = a.getOrElse(i) { 0 }
            val db = b.getOrElse(i) { 0 }
            if (da != db) return da > db
        }
        return false
    }

    private fun parseVersion(v: String): List<Int> =
        Regex("""\d+""").findAll(v).map { it.value.toInt() }.toList().ifEmpty { listOf(0) }
}
