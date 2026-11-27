package com.silent.vpn.util

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri

/**
 * YuMoney в китайском браузере по умолчанию не открывается.
 * Всегда пробуем Chrome / Яндекс, не системный default.
 */
object PaymentBrowser {
    private val PREFERRED_PACKAGES = listOf(
        "com.android.chrome",
        "com.chrome.beta",
        "com.chrome.dev",
        "com.google.android.apps.chrome",
        "com.yandex.browser",
        "com.yandex.browser.beta",
        "com.yandex.browser.alpha",
        "org.mozilla.firefox",
        "com.microsoft.emmx",
        "com.brave.browser",
        "com.sec.android.app.sbrowser",
    )

    fun openPaymentUrl(context: Context, url: String) {
        val uri = Uri.parse(url)
        val preferred = preferredIntent(context, uri)
        if (preferred != null) {
            DebugLog.i("PaymentBrowser", "open ${preferred.`package`}")
            context.startActivity(preferred)
            return
        }
        DebugLog.w("PaymentBrowser", "fallback default browser")
        context.startActivity(Intent(Intent.ACTION_VIEW, uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    internal fun checkoutPackage(context: Context): String? =
        (preferredIntent(context, Uri.parse("https://yoomoney.ru/"))?.`package`
            ?: defaultHttpsBrowserPackage(context))?.takeUnless { it == "android" }

    private fun preferredIntent(context: Context, uri: Uri): Intent? {
        val pm = context.packageManager
        for (pkg in PREFERRED_PACKAGES) {
            if (!isInstalled(pm, pkg)) continue
            val intent = Intent(Intent.ACTION_VIEW, uri).apply {
                setPackage(pkg)
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            if (intent.resolveActivity(pm) != null) return intent
        }
        return null
    }

    fun defaultHttpsBrowserPackage(context: Context): String? {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("https://yoomoney.ru/"))
        return intent.resolveActivity(context.packageManager)?.packageName
    }

    private fun isInstalled(pm: PackageManager, pkg: String): Boolean = runCatching {
        pm.getPackageInfo(pkg, 0)
        true
    }.getOrDefault(false)
}
