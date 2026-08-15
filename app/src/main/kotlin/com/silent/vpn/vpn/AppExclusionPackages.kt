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

data class AppTunnelPolicy(
    /** true = БС: только эти пакеты через VPN (includeApplications). */
    val whitelist: Boolean,
    val packages: Set<String>,
)

/**
 * Main VPN: Silent в туннеле (API 10.66.66.1); VK — вне туннеля.
 * ЧС: excludeApplications(user + VK [+ self если нужно]).
 * БС: includeApplications(user ∪ self); VK не включаем.
 */
fun resolveAppTunnelPolicy(context: Context, includeAppInTunnel: Boolean = false): AppTunnelPolicy {
    val prefs = SilentPrefs.open(context)
    val userSelected = prefs.getString(SilentRepository.PREF_EXCLUDED_APPS, "")
        ?.split(",")
        ?.filter { it.isNotBlank() }
        ?.toSet()
        ?: emptySet()
    val pm = context.packageManager

    // Стабильность mobile first: применяем только ЧС-модель (как в 1.0.160),
    // чтобы пользовательские режимы БС не выводили приложения из VPN-туннеля.
    // Это устраняет сценарий "VPN подключен, но сайты/приложения не грузятся на LTE".

    val excluded = LinkedHashSet<String>()
    if (!includeAppInTunnel) {
        excluded.add(context.packageName)
    }
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(userSelected)
    val filtered = excluded.filter { isPackageInstalled(pm, it) }.toSet()
    DebugLog.i("AppExclusions", "ЧС excludeApplications: ${filtered.size}")
    return AppTunnelPolicy(whitelist = false, packages = filtered)
}

/** @deprecated используйте [resolveAppTunnelPolicy] */
fun resolveExcludedAppPackages(context: Context, includeAppInTunnel: Boolean = false): Set<String> {
    val policy = resolveAppTunnelPolicy(context, includeAppInTunnel)
    return if (policy.whitelist) emptySet() else policy.packages
}

private fun isPackageInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
    pm.getPackageInfo(pkg, 0)
    true
}.getOrDefault(false)
