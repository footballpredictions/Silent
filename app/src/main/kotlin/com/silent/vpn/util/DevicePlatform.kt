package com.silent.vpn.util

import android.app.UiModeManager
import android.content.Context
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.platform.LocalContext

/**
 * Определение Android TV / Google TV / Fire TV и приставок без touch-экрана.
 * Один APK для телефона и TV; в API сессии у TV тип [API_DEVICE_TYPE_TV].
 */
object DevicePlatform {
    const val API_DEVICE_TYPE_PHONE = "android"
    const val API_DEVICE_TYPE_TV = "android_tv"
    const val OTA_PLATFORM = "android"

    @Volatile
    private var cachedIsTv: Boolean? = null

    fun isTv(context: Context): Boolean {
        cachedIsTv?.let { return it }
        val result = detectTv(context)
        cachedIsTv = result
        return result
    }

    fun apiDeviceType(context: Context): String =
        if (isTv(context)) API_DEVICE_TYPE_TV else API_DEVICE_TYPE_PHONE

    fun getDeviceDisplayName(context: Context): String {
        val manufacturer = (Build.MANUFACTURER ?: "").trim()
        val model = (Build.MODEL ?: "").trim()
        val raw = when {
            model.isEmpty() -> manufacturer
            manufacturer.isEmpty() -> model
            model.startsWith(manufacturer, ignoreCase = true) -> model
            else -> "$manufacturer $model"
        }.trim()
        val formatted = raw.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
            .ifBlank { if (isTv(context)) "Android TV" else "Android" }
        return formatted.take(64)
    }

    private fun detectTv(context: Context): Boolean {
        val uiMode = context.resources.configuration.uiMode and Configuration.UI_MODE_TYPE_MASK
        if (uiMode == Configuration.UI_MODE_TYPE_TELEVISION) return true

        val pm = context.packageManager
        if (pm.hasSystemFeature(PackageManager.FEATURE_LEANBACK)) return true
        if (pm.hasSystemFeature(PackageManager.FEATURE_TELEVISION)) return true

        val uiModeManager = context.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
        if (uiModeManager?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION) return true

        if (isKnownTvHardware()) return true

        // Многие приставки и Smart TV без leanback, но без сенсорного экрана.
        if (!pm.hasSystemFeature(PackageManager.FEATURE_TOUCHSCREEN)) {
            if (uiMode == Configuration.UI_MODE_TYPE_NORMAL ||
                uiMode == Configuration.UI_MODE_TYPE_TELEVISION
            ) {
                return true
            }
        }
        return false
    }

    private fun isKnownTvHardware(): Boolean {
        val model = (Build.MODEL ?: "").lowercase()
        val man = (Build.MANUFACTURER ?: "").lowercase()
        val product = (Build.PRODUCT ?: "").lowercase()
        val device = (Build.DEVICE ?: "").lowercase()

        if (man == "amazon" && (model.startsWith("aft") || product.contains("fire_tv"))) return true
        // Ugoos / Amlogic STB (TOX1, X3 и т.п.) — часто без LEANBACK, но TV-приставки.
        if (man.contains("ugoos") || model.contains("ugoos") || product.contains("ugoos")) return true
        if (model.contains("tox1") || device.contains("tox1") || product.contains("tox1")) return true
        if (man.contains("amlogic") || device.contains("amlogic") || product.contains("amlogic")) return true
        if (model.contains("android tv") || model.contains("google tv")) return true
        if (model.contains("bravia") || model.contains("philips tv")) return true
        if (model.endsWith("_tv") || device.endsWith("_tv") || product.endsWith("_tv")) return true
        if (model.contains("atv") || product.contains("atv") || device.contains("atv")) return true
        if (model.contains("stb") || product.contains("stb") || device.contains("stb")) return true
        if (model.contains("box") && !model.contains("xbox")) return true
        return false
    }

    fun primaryAbi(): String = Build.SUPPORTED_ABIS.firstOrNull() ?: "unknown"

    /** armeabi-v7a TV/приставки и слабые 32-bit телефоны. */
    fun isLowEndArm32(context: Context): Boolean = primaryAbi() == "armeabi-v7a"

    /** Bootstrap VPN на экране входа: TV 3 мин, телефон 2 мин. */
    fun bootstrapSessionMs(context: Context): Long =
        if (isTv(context)) 3 * 60 * 1000L else 2 * 60 * 1000L

    fun bootstrapSessionMinutes(context: Context): Int =
        if (isTv(context)) 3 else 2

    fun hasWebView(context: Context): Boolean = runCatching {
        android.webkit.WebView(context.applicationContext).destroy()
        true
    }.getOrDefault(false)
}

val LocalIsTv = staticCompositionLocalOf { false }

@Composable
fun rememberIsTv(): Boolean {
    val context = LocalContext.current
    return DevicePlatform.isTv(context)
}
