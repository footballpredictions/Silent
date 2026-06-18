package com.silent.vpn.vk

import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

object VkOAuthExchange {
    private const val TAG = "VkOAuthExchange"
    private val client = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    data class TokenResult(val accessToken: String, val userId: Long)

    suspend fun exchangeCode(code: String): Result<TokenResult> = withContext(Dispatchers.IO) {
        runCatching {
            val body = FormBody.Builder()
                .add("grant_type", "authorization_code")
                .add("client_id", VkOAuthConfig.CLIENT_ID.toString())
                .add("client_secret", VkOAuthConfig.CLIENT_SECRET)
                .add("redirect_uri", VkOAuthConfig.REDIRECT_URI)
                .add("code", code)
                .build()
            val req = Request.Builder()
                .url("https://oauth.vk.com/token")
                .post(body)
                .header("User-Agent", VkOAuthConfig.VK_API_USER_AGENT)
                .build()
            client.newCall(req).execute().use { resp ->
                val text = resp.body?.string() ?: throw IllegalStateException("Пустой ответ VK OAuth")
                DebugLog.i(TAG, "token exchange HTTP ${resp.code}")
                val json = JSONObject(text)
                if (json.has("error")) {
                    val msg = json.optString("error_description", json.optString("error", "OAuth error"))
                    throw IllegalStateException(msg)
                }
                val token = json.optString("access_token")
                if (token.isBlank()) throw IllegalStateException("VK не вернул access_token")
                val userId = json.optLong("user_id", 0L)
                TokenResult(token, userId)
            }
        }.onFailure { DebugLog.e(TAG, "exchangeCode failed", it) }
    }
}
