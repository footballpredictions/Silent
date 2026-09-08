package com.silent.vpn.policy

/**
 * Google Sign-In в приложениях (Gemini, ChatGPT, Claude) идёт через GMS
 * и Chrome Custom Tabs. Если эти пакеты в ЧС, а само ИИ-приложение в туннеле —
 * OAuth видит два IP и отказывается входить. Браузер при этом может работать:
 * пользователь открыл Яндекс/Samsung, а Custom Tabs всегда берут Chrome.
 */
object GoogleAuthTunnelPolicy {

    val MUST_STAY_IN_TUNNEL: Set<String> = setOf(
        "com.google.android.gms",
        "com.google.android.gsf",
        "com.google.android.gsf.login",
        "com.android.vending",
        "com.google.android.webview",
        "com.google.android.webview.beta",
        "com.android.webview",
        "com.google.android.captiveportallogin",
        "com.android.chrome",
        "com.chrome.beta",
        "com.chrome.dev",
        "com.chrome.canary",
        "com.google.android.apps.chrome",
    )

    fun excludeWithoutGoogleAuth(packages: Set<String>): Set<String> =
        packages.filterNot { it in MUST_STAY_IN_TUNNEL }.toSet()

    fun droppedFromExclude(packages: Set<String>): Set<String> =
        packages.filter { it in MUST_STAY_IN_TUNNEL }.toSet()
}
