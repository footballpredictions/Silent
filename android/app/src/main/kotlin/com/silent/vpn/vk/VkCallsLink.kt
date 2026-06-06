package com.silent.vpn.vk

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri

/** Открыть раздел «Звонки» в приложении VK (не в браузере). */
object VkCallsLink {
    private val VK_APP_PACKAGES = listOf(
        "com.vkontakte.android",
        "com.vk.calls",
    )

    private val IN_APP_URIS = listOf(
        "vkontakte://vk.com/calls",
        "vkontakte://calls",
        "https://vk.com/calls",
        "https://vk.ru/calls",
        "https://m.vk.com/calls",
    )

    fun openCalls(context: Context, webUrl: String? = null) {
        val pm = context.packageManager
        val extras = webUrl?.trim()?.takeIf { it.isNotBlank() }?.let { listOf(it) }.orEmpty()
        val candidates = (IN_APP_URIS + extras).distinct()

        for (pkg in VK_APP_PACKAGES) {
            if (!isInstalled(pm, pkg)) continue
            for (uri in candidates) {
                if (launch(context, Uri.parse(uri), pkg, pm)) return
            }
        }

        val browserUrl = extras.firstOrNull() ?: "https://vk.com/calls"
        launch(context, Uri.parse(browserUrl), packageName = null, pm = pm)
    }

    private fun launch(context: Context, uri: Uri, packageName: String?, pm: PackageManager): Boolean {
        val intent = Intent(Intent.ACTION_VIEW, uri)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (packageName != null) intent.setPackage(packageName)
        if (intent.resolveActivity(pm) == null) return false
        return runCatching {
            context.startActivity(intent)
            true
        }.getOrDefault(false)
    }

    private fun isInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
        pm.getPackageInfo(pkg, 0)
        true
    }.getOrDefault(false)
}
