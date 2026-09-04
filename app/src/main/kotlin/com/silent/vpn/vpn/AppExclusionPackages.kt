package com.silent.vpn.vpn

import android.content.Context
import android.content.pm.PackageManager
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.policy.AppExclusionsPersist
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
    /** true = БС (зарезервировано). Сейчас main VPN всегда ЧС-модель. */
    val whitelist: Boolean,
    val packages: Set<String>,
)

/**
 * Main VPN: только ЧС-модель в туннеле (как 1.0.160/163).
 * Persist БС/ЧС (режим + оба списка) живёт в prefs и UI — здесь **не затираем**.
 * Непустой БС в туннеле пока no-op (full tunnel кроме Silent+VK), иначе includeApplications
 * без Silent роняет DNS. Точечный фикс маршрутизации БС — отдельно.
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

    // БС: не трогаем prefs (раньше heal сбрасывал режим и списки).
    // В туннель — только ЧС-пакеты; при активном БС user-exclude пустой (full tunnel + Silent/VK out).
    val userForTunnel = if (intent.whitelist) {
        DebugLog.i(
            "AppExclusions",
            "БС mode persisted (${intent.userPackages.size} apps) — tunnel ЧС-safe (no wipe prefs)",
        )
        emptySet()
    } else {
        intent.userPackages
    }

    val excluded = LinkedHashSet<String>()
    if (!includeAppInTunnel) {
        excluded.add(context.packageName)
    }
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(userForTunnel)
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

