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
 * @param isBootstrap bootstrap VPN: app внутри туннеля для API при логине.
 * Основной VPN: app вне туннеля — libclient/TURN напрямую (белые списки).
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
    if (!isBootstrap) {
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
