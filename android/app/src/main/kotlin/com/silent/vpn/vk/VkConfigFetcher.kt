package com.silent.vpn.vk

import com.google.gson.Gson
import com.google.gson.JsonObject
import com.silent.vpn.data.VpnConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

object VkConfigFetcher {
    private const val GROUP_ID = 239092728L
    private const val API = "https://api.vk.com/method"
    private const val CONFIG_MAX_AGE_SEC = 3600

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    suspend fun fetchConfig(vkUserId: Long, accessToken: String?): VpnConfig? = withContext(Dispatchers.IO) {
        if (accessToken.isNullOrBlank()) return@withContext null
        val peerId = -GROUP_ID
        val url = "$API/messages.getHistory?peer_id=$peerId&count=20&rev=0&access_token=$accessToken&v=5.199"
        try {
            val resp = client.newCall(Request.Builder().url(url).get().build()).execute()
            val body = resp.body?.string() ?: return@withContext null
            val json = Gson().fromJson(body, JsonObject::class.java)
            if (json.has("error")) return@withContext null
            val items = json.getAsJsonObject("response")?.getAsJsonArray("items") ?: return@withContext null
            var best: VpnConfig? = null
            var bestTs = 0L
            for (i in 0 until items.size()) {
                val item = items[i].asJsonObject
                val fromId = item.get("from_id")?.asLong ?: continue
                if (fromId > 0) continue
                val text = item.get("text")?.asString ?: continue
                if (!text.startsWith("SILENT:v1:")) continue
                val ts = item.get("date")?.asLong ?: 0L
                if (System.currentTimeMillis() / 1000 - ts > CONFIG_MAX_AGE_SEC) continue
                val cfg = VkConfigCrypto.decryptMessage(vkUserId, text) ?: continue
                if (cfg.vk_hashes.isEmpty()) continue
                if (ts >= bestTs) {
                    bestTs = ts
                    best = cfg
                }
            }
            best
        } catch (_: Exception) {
            null
        }
    }
}
