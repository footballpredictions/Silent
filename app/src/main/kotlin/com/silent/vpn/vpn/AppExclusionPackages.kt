package com.silent.vpn.vpn

import android.content.Context
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.policy.AppExclusionsPersist
import com.silent.vpn.policy.AppTunnelRouting
import com.silent.vpn.policy.GoogleAuthTunnelPolicy
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
    "ru.yoo.money",
    "ru.yandex.money",
    "com.yandex.money",
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
    /** true = БС: packages = complement (мимо VPN), выбранные остаются в туннеле. */
    val whitelist: Boolean,
    val packages: Set<String>,
)

/**
 * Main VPN: ЧС и БС кладут bypass-пакеты в excludeApplications.
 * БС = все установленные минус выбранные. Silent/VK всегда в exclude, кроме overlay.
 */
fun resolveAppTunnelPolicy(context: Context, includeAppInTunnel: Boolean = false): AppTunnelPolicy {
    val prefs = SilentPrefs.open(context)
    val dual = prefs.getBoolean(SilentRepository.PREF_EXCLUSIONS_DUAL_MIGRATED, false)
    val whitelistMode = prefs.getBoolean(SilentRepository.PREF_EXCLUSIONS_WHITELIST, false)
    fun parse(key: String): Set<String> =
        prefs.getString(key, "")?.split(",")?.filter { it.isNotBlank() }?.toSet() ?: emptySet()
    val state = AppExclusionsPersist.hydrate(
        selectedIds = parse(SilentRepository.PREF_EXCLUDED_APPS),
        whitelist = whitelistMode,
        blacklistAppIds = if (dual) parse(SilentRepository.PREF_EXCLUSIONS_BLACKLIST) else null,
        whitelistAppIds = if (dual) parse(SilentRepository.PREF_EXCLUSIONS_WHITELIST_APPS) else null,
    )
    val intent = AppExclusionsPersist.tunnelIntent(state)
    val pm = context.packageManager
    val installed = installedBypassCandidates(pm, context.packageName)
    val built = AppTunnelRouting.fromIntent(
        intent = intent,
        selfPackage = context.packageName,
        includeAppInTunnel = includeAppInTunnel,
        vkPackages = VK_TUNNEL_PACKAGES,
        installedPackages = installed,
    )
    val filtered = built.packages.filter { isPackageInstalled(pm, it) }.toSet()
    if (built.whitelist) {
        DebugLog.i("AppExclusions", "БС exclude complement: ${filtered.size} (keep=${intent.userPackages.size})")
    } else {
        val droppedAuth = GoogleAuthTunnelPolicy.droppedFromExclude(intent.userPackages)
        if (droppedAuth.isNotEmpty()) {
            DebugLog.i("AppExclusions", "Google auth kept in tunnel: ${droppedAuth.joinToString()}")
        }
        DebugLog.i("AppExclusions", "ЧС excludeApplications: ${filtered.size}")
    }
    return AppTunnelPolicy(whitelist = built.whitelist, packages = filtered)
}

/** @deprecated используйте [resolveAppTunnelPolicy] */
fun resolveExcludedAppPackages(context: Context, includeAppInTunnel: Boolean = false): Set<String> {
    return resolveAppTunnelPolicy(context, includeAppInTunnel).packages
}

/** Лаунчер + пользовательские пакеты — тот же круг, что список исключений. */
private fun installedBypassCandidates(pm: PackageManager, selfPackage: String): Set<String> {
    val fromPm = runCatching {
        pm.getInstalledApplications(PackageManager.GET_META_DATA)
    }.getOrDefault(emptyList())
    val launcher = runCatching {
        val launch = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        @Suppress("DEPRECATION")
        pm.queryIntentActivities(launch, PackageManager.MATCH_ALL)
            .mapNotNull { it.activityInfo?.packageName }
            .toSet()
    }.getOrDefault(emptySet())
    val out = LinkedHashSet<String>()
    for (info in fromPm) {
        val pkg = info.packageName ?: continue
        if (pkg == selfPackage || pkg in VK_TUNNEL_PACKAGES) continue
        val system = info.flags and ApplicationInfo.FLAG_SYSTEM != 0
        val updated = info.flags and ApplicationInfo.FLAG_UPDATED_SYSTEM_APP != 0
        if (!system || updated || pkg in launcher) out.add(pkg)
    }
    for (pkg in launcher) {
        if (pkg != selfPackage && pkg !in VK_TUNNEL_PACKAGES) out.add(pkg)
    }
    return out
}

private fun isPackageInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
    pm.getPackageInfo(pkg, 0)
    true
}.getOrDefault(false)

