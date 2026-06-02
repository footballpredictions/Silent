package com.silent.vpn.vpn

import android.content.Context
import android.content.pm.PackageManager
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository

/** Пакеты VK — всегда вне туннеля (TURN), как в proxy-turn-vk-android. */
val VK_TUNNEL_PACKAGES = setOf(
    "com.vkontakte.android",
    "com.vk.calls",
    "com.vk.im",
)

/**
 * Список для [com.wireguard.config.Interface.Builder.excludeApplications].
 * В storage всегда лежит blacklist (отмеченные = вне VPN); режим БС инвертируется в UI при переключении.
 */
/**
 * @param isBootstrap bootstrap VPN на экране входа; основной VPN использует те же правила маршрутизации.
 * Наш app всегда внутри VPN — API (10.66.66.1) через туннель; TURN IP исключён из AllowedIPs (split-tunnel).
 */
fun resolveExcludedAppPackages(context: Context, isBootstrap: Boolean = false): Set<String> {
    val prefs = SilentPrefs.open(context)
    val userSelected = prefs.getString(SilentRepository.PREF_EXCLUDED_APPS, "")
        ?.split(",")
        ?.filter { it.isNotBlank() }
        ?.toSet()
        ?: emptySet()

    val pm = context.packageManager
    val excluded = LinkedHashSet<String>()
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(userSelected)

    return excluded.filter { pkg -> isPackageInstalled(pm, pkg) }.toSet()
}

private fun isPackageInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
    pm.getPackageInfo(pkg, 0)
    true
}.getOrDefault(false)
