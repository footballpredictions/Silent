package com.silent.vpn.vk

import android.net.Uri

/** Android VK OAuth (code flow) — token на устройстве, без VK ID «в один клик». */
object VkOAuthUrls {
    fun buildAuthorizeUrl(state: String): String {
        return Uri.Builder()
            .scheme("https")
            .authority("oauth.vk.ru")
            .appendPath("authorize")
            .appendQueryParameter("client_id", VkOAuthConfig.CLIENT_ID.toString())
            .appendQueryParameter("redirect_uri", VkOAuthConfig.REDIRECT_URI)
            .appendQueryParameter("response_type", "code")
            .appendQueryParameter("scope", "offline")
            .appendQueryParameter("state", state)
            .appendQueryParameter("display", "mobile")
            .appendQueryParameter("revoke", "1")
            .build()
            .toString()
    }
}
