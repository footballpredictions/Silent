package com.silent.vpn.vk

object VkOAuthConfig {
    const val CLIENT_ID = 6287487
    const val CLIENT_SECRET = "VeWdmVclDCtn6ihuP1nt"
    const val REDIRECT_URI = "https://oauth.vk.com/blank.html"

    /** Обычный Chrome Mobile — иначе VK предлагает «войти через приложение» (vkontakte://). */
    const val OAUTH_WEB_USER_AGENT =
        "Mozilla/5.0 (Linux; Android 14; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"

    const val VK_API_USER_AGENT =
        "VKAndroidApp/8.10-17765 (Android 14; SDK 34; arm64-v8a; Google Pixel 8; ru; 2560x1080)"
}
