package com.silent.vpn.vpn

import android.content.Context
import android.content.pm.PackageManager
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.util.DebugLog

/** Пакеты VK — всегда вне туннеля (TURN), как в proxy-turn-vk-android. */
val VK_TUNNEL_PACKAGES = setOf(
    "com.vkontakte.android",
    "com.vk.calls",
    "com.vk.im",
)

/**
 * Bootstrap (шаг 1): в VPN только Silent + браузеры + почта — ссылки из писем открываются с телефона.
 * Остальные приложения (VK и т.д.) VPN не затрагивает.
 */
private val BOOTSTRAP_COMPANION_PACKAGES = listOf(
    "com.android.chrome",
    "com.chrome.beta",
    "com.chrome.dev",
    "com.android.browser",
    "org.mozilla.firefox",
    "com.opera.browser",
    "com.opera.mini.native",
    "com.brave.browser",
    "com.microsoft.emmx",
    "com.sec.android.app.sbrowser",
    "com.yandex.browser",
    "com.yandex.browser.beta",
    "com.yandex.browser.alpha",
    "com.yandex.searchapp",
    "ru.yandex.searchplugin",
    "com.google.android.gm",
    "com.microsoft.office.outlook",
    "com.yahoo.mobile.client.android.mail",
    "ru.mail.mailapp",
    "com.my.mail",
    "ru.yandex.mail",
    "com.yandex.mail",
    "com.samsung.android.email.provider",
    "com.google.android.apps.messaging",
)

fun resolveBootstrapIncludedApps(context: Context): Set<String> {
    val pm = context.packageManager
    val out = linkedSetOf(context.packageName)
    for (pkg in BOOTSTRAP_COMPANION_PACKAGES) {
        if (isPackageInstalled(pm, pkg)) out.add(pkg)
    }
    DebugLog.i("BootstrapVpn", "included apps: ${out.size} (${out.joinToString { it.substringAfterLast('.') }})")
    return out
}

/**
 * Main VPN: Silent и VK вне WG (libclient/TURN напрямую на белых списках).
 * Bootstrap: includeApplications — Silent + браузеры + почта.
 */
fun resolveExcludedAppPackages(context: Context, includeAppInTunnel: Boolean = false): Set<String> {
    val prefs = SilentPrefs.open(context)
    val userSelected = prefs.getString(SilentRepository.PREF_EXCLUDED_APPS, "")
        ?.split(",")
        ?.filter { it.isNotBlank() }
        ?.toSet()
        ?: emptySet()

    val pm = context.packageManager
    val excluded = LinkedHashSet<String>()
    if (!includeAppInTunnel) {
        excluded.add(context.packageName)
    }
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(userSelected)

    return excluded.filter { pkg -> isPackageInstalled(pm, pkg) }.toSet()
}

private fun isPackageInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
    pm.getPackageInfo(pkg, 0)
    true
}.getOrDefault(false)
