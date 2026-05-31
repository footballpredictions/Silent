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
fun resolveExcludedAppPackages(context: Context): Set<String> {
    val prefs = SilentPrefs.open(context)
    val userSelected = prefs.getString(SilentRepository.PREF_EXCLUDED_APPS, "")
        ?.split(",")
        ?.filter { it.isNotBlank() }
        ?.toSet()
        ?: emptySet()

    val pm = context.packageManager
    // Как в proxy-turn-vk-android: наш app исключаем из VPN-туннеля.
    // Тогда libclient дотягивается до TURN-серверов напрямую (без WG-петли),
    // AllowedIPs остаётся 0.0.0.0/0 (простой полный туннель для остальных приложений),
    // а API-вызовы приложения идут напрямую к публичному серверу.
    val excluded = LinkedHashSet<String>()
    excluded.add(context.packageName)          // собственный пакет — всегда вне туннеля
    excluded.addAll(VK_TUNNEL_PACKAGES)
    excluded.addAll(userSelected)

    return excluded.filter { pkg -> isPackageInstalled(pm, pkg) }.toSet()
}

private fun isPackageInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
    pm.getPackageInfo(pkg, 0)
    true
}.getOrDefault(false)
