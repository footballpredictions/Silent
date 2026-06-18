package com.silent.vpn.vk

import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * VK API на устройстве: calls.start + users.get.
 */
object VkCallApi {
    private const val TAG = "VkCallApi"
    private const val API_VERSION = "5.199"
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    private val hashRegex = Regex("/join/([A-Za-z0-9_\\-]+)")
    private val apiHosts = listOf("https://api.vk.ru/method/", "https://api.vk.com/method/")

    suspend fun createCallHash(accessToken: String): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val body = vkApiPost("calls.start", accessToken)
            if (body.has("error")) {
                val err = body.getJSONObject("error")
                val code = err.optInt("error_code", 0)
                val msg = err.optString("error_msg", "calls.start error")
                throw IllegalStateException(if (code > 0) "[$code] $msg" else msg)
            }
            val joinLink = body.getJSONObject("response").optString("join_link")
            extractHash(joinLink) ?: throw IllegalStateException("join_link без хеша")
        }.onFailure { DebugLog.e(TAG, "createCallHash failed", it) }
    }

    suspend fun resolveUserId(accessToken: String): Result<Long> = withContext(Dispatchers.IO) {
        runCatching {
            val body = vkApiPost("users.get", accessToken)
            if (body.has("error")) {
                val err = body.getJSONObject("error")
                throw IllegalStateException(err.optString("error_msg", "users.get error"))
            }
            val arr = body.getJSONArray("response")
            if (arr.length() == 0) throw IllegalStateException("users.get пустой")
            arr.getJSONObject(0).getLong("id")
        }.onFailure { DebugLog.e(TAG, "resolveUserId failed", it) }
    }

    fun extractHash(joinLink: String): String? {
        hashRegex.find(joinLink)?.groupValues?.getOrNull(1)?.let { return it }
        val s = joinLink.trim()
        if (s.length >= 8 && s.all { it.isLetterOrDigit() || it == '-' || it == '_' }) return s
        return null
    }

    private fun vkApiPost(method: String, token: String): JSONObject {
        val form = FormBody.Builder()
            .add("access_token", token)
            .add("v", API_VERSION)
            .build()
        var lastError: Exception? = null
        for (host in apiHosts) {
            try {
                val req = Request.Builder()
                    .url("$host$method")
                    .post(form)
                    .header("User-Agent", VkOAuthConfig.VK_API_USER_AGENT)
                    .build()
                client.newCall(req).execute().use { resp ->
                    val text = resp.body?.string() ?: throw IllegalStateException("Пустой ответ VK API")
                    if (!resp.isSuccessful) throw IllegalStateException("VK HTTP ${resp.code}")
                    return JSONObject(text)
                }
            } catch (e: Exception) {
                lastError = e
                DebugLog.w(TAG, "vkApiPost $host$method failed: ${e.message}")
            }
        }
        throw lastError ?: IllegalStateException("VK API недоступен")
    }
}
