package com.silent.vpn.vk

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri

/** Открыть раздел «Звонки»: VK → VK Звонки → браузер. */
object VkCallsLink {
    private const val PKG_VK = "com.vkontakte.android"
    private const val PKG_VK_CALLS = "com.vk.calls"

    private val VK_URIS = listOf(
        "vkontakte://vk.com/calls",
        "vkontakte://calls",
        "https://vk.com/calls",
        "https://vk.ru/calls",
        "https://m.vk.com/calls",
    )

    private val VK_CALLS_URIS = listOf(
        "vkcalls://calls",
        "vkontakte://vk.com/calls",
        "vkontakte://calls",
        "https://vk.com/calls",
        "https://vk.ru/calls",
    )

    fun openCalls(context: Context, webUrl: String? = null) {
        val pm = context.packageManager
        val webExtras = webUrl?.trim()?.takeIf { it.isNotBlank() }?.let { listOf(it) }.orEmpty()

        if (tryOpenInPackage(context, pm, PKG_VK, VK_URIS + webExtras)) return
        if (tryOpenInPackage(context, pm, PKG_VK_CALLS, VK_CALLS_URIS + webExtras)) return

        val browserUrl = webExtras.firstOrNull() ?: "https://vk.com/calls"
        launch(context, Uri.parse(browserUrl), packageName = null, pm = pm)
    }

    private fun tryOpenInPackage(
        context: Context,
        pm: PackageManager,
        packageName: String,
        uris: List<String>,
    ): Boolean {
        if (!isInstalled(pm, packageName)) return false
        for (uri in uris.distinct()) {
            if (launch(context, Uri.parse(uri), packageName, pm)) return true
        }
        return false
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
