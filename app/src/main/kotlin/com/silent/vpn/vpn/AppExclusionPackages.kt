package com.silent.vpn.vpn

import android.content.Context
import android.content.pm.PackageManager
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.PaymentBrowser

/** Пакеты VK — всегда вне туннеля (TURN), как в proxy-turn-vk-android. */
val VK_TUNNEL_PACKAGES = setOf(
    "com.vkontakte.android",
    "com.vk.calls",
    "com.vk.im",
)

/**
 * Bootstrap (шаг 1 / оплата): в VPN Silent + браузеры + почта + YuMoney/Сбер.
 * YuMoney QuickPay часто открывает SberPay → приложение СберБанк Онлайн;
 * без него на LTE с блокировкой оплата обрывается.
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
    "com.huawei.browser",
    "com.mi.globalbrowser",
    "com.miui.browser",
    "com.vivo.browser",
    "com.coloros.browser",
    "com.heytap.browser",
    "com.uc.browser",
    "com.UCMobile",
    "com.quark.browser",
    "mark.via.gp",
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
    // YuMoney / кошелёк (если открывается как приложение, не только сайт)
    "ru.yoo.money",
    "ru.yandex.money",
    "com.yandex.money",
    // SberPay / СберБанк Онлайн — deep-link с страницы YuMoney
    "ru.sberbankmobile",
    "ru.sberbankmobile_alpha",
    "ru.sberbank.sberbankid",
    "ru.sberbank.salute",
)

fun resolveBootstrapIncludedApps(context: Context): Set<String> {
    val pm = context.packageManager
    val out = linkedSetOf(context.packageName)
    for (pkg in BOOTSTRAP_COMPANION_PACKAGES) {
        if (isPackageInstalled(pm, pkg)) out.add(pkg)
    }
    PaymentBrowser.defaultHttpsBrowserPackage(context)?.let { defPkg ->
        if (isPackageInstalled(pm, defPkg)) out.add(defPkg)
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
    val whitelistMode = prefs.getBoolean(SilentRepository.PREF_EXCLUSIONS_WHITELIST, false)
    val userSelected = prefs.getString(SilentRepository.PREF_EXCLUDED_APPS, "")
        ?.split(",")
        ?.filter { it.isNotBlank() }
        ?.toSet()
        ?: emptySet()
    val pm = context.packageManager

    // Стабильность mobile first: применяем только ЧС-модель (как в 1.0.160),
    // чтобы пользовательские режимы БС не выводили приложения из VPN-туннеля.
    // Это устраняет сценарий "VPN подключен, но сайты/приложения не грузятся на LTE".

    // Legacy-heal: если в prefs остался БС-режим, его список трактовался как ЧС и
    // выборочно "выбрасывал" приложения из VPN (симптом: Telegram работает, YouTube нет).
    // Для стабильности main VPN принудительно держим ЧС-модель и сбрасываем БС-хвост.
    val effectiveSelected = if (whitelistMode) {
        if (userSelected.isNotEmpty()) {
            DebugLog.w("AppExclusions", "legacy whitelist detected (${userSelected.size}) -> reset to blacklist")
        } else {
            DebugLog.w("AppExclusions", "legacy whitelist flag detected -> reset to blacklist")
        }
        prefs.edit()
            .putBoolean(SilentRepository.PREF_EXCLUSIONS_WHITELIST, false)
            .putString(SilentRepository.PREF_EXCLUDED_APPS, "")
            .apply()
        emptySet()
    } else {
        userSelected
    }

    val excluded = LinkedHashSet<String>()
    if (!includeAppInTunnel) {
        excluded.add(context.packageName)
    }
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(effectiveSelected)
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
