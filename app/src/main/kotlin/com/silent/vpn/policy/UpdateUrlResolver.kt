package com.silent.vpn.policy

import com.silent.vpn.policy.VpnNetworkConstants.DEFAULT_SERVER_HOST
import com.silent.vpn.policy.VpnNetworkConstants.TUNNEL_API_BASE
import com.silent.vpn.policy.VpnNetworkConstants.WG_TUNNEL_GATEWAY

/** Чистая логика URL для OTA (без Retrofit/Android). */
object UpdateUrlResolver {

    data class OtaUrlInput(
        val onMobileData: Boolean,
        val appExcludedFromVpn: Boolean,
        val mainVpnTunnelUp: Boolean,
        val isBootstrapMode: Boolean,
        val publicServerUrl: String,
        val preferredHttpsBase: String? = null,
        val tunnelProxyActive: Boolean = false,
        val githubDownloadUrl: String? = null,
        val downloadUrl: String? = null,
        val tunnelDownloadPath: String? = null,
        val otaPlatform: String = "android",
    )

    /**
     * Мобильный интернет (часто белые списки): APK только через tunnel API при живом VPN.
     * Wi‑Fi — public/GitHub, VPN не нужен.
     */
    fun shouldUseTunnelUpdateDownload(input: OtaUrlInput): Boolean {
        if (!input.onMobileData) return false
        if (input.isBootstrapMode) return false
        return input.mainVpnTunnelUp
    }

    /** Скачивание OTA на LTE требует включённый VPN (обход whitelist). */
    fun requiresVpnToDownloadUpdate(onMobileData: Boolean): Boolean = onMobileData

    fun canStartUpdateDownload(onMobileData: Boolean, vpnReady: Boolean): Boolean =
        !requiresVpnToDownloadUpdate(onMobileData) || vpnReady

    fun resolveUpdateDownloadBase(input: OtaUrlInput): String {
        if (!input.onMobileData || input.appExcludedFromVpn) {
            input.preferredHttpsBase?.trimEnd('/')?.takeIf { it.startsWith("https://") }?.let { return it }
            return input.publicServerUrl.trimEnd('/').ifBlank { "https://$DEFAULT_SERVER_HOST" }
        }
        val base = input.preferredHttpsBase?.trimEnd('/').orEmpty()
        if (isTunnelApiBase(base) || input.tunnelProxyActive) return TUNNEL_API_BASE
        if (base.startsWith("http://")) {
            if (input.appExcludedFromVpn && !input.tunnelProxyActive) {
                return "https://$DEFAULT_SERVER_HOST"
            }
            return base
        }
        if (base.contains(Regex("""\d+\.\d+\.\d+\.\d+"""))) return "https://$DEFAULT_SERVER_HOST"
        if (base.startsWith("https://")) return base
        return "https://$DEFAULT_SERVER_HOST"
    }

    fun joinUpdateUrl(base: String, downloadPath: String): String {
        if (downloadPath.startsWith("http://") || downloadPath.startsWith("https://")) return downloadPath
        val path = if (downloadPath.startsWith("/")) downloadPath else "/$downloadPath"
        return base.trimEnd('/') + path.replace(" ", "%20")
    }

    fun resolveUpdateDownloadUrl(input: OtaUrlInput): String? {
        if (shouldUseTunnelUpdateDownload(input)) {
            val path = input.tunnelDownloadPath?.trim()?.takeIf { it.isNotBlank() }
                ?: "/api/updates/download/${input.otaPlatform}"
            return joinUpdateUrl(TUNNEL_API_BASE, path)
        }
        val gh = input.githubDownloadUrl?.trim()?.takeIf { it.startsWith("http") }
        val absolute = input.downloadUrl?.trim()?.takeIf { it.startsWith("http") }
        if (gh != null) return gh
        if (absolute != null) return absolute
        val rel = input.downloadUrl?.trim().orEmpty()
        if (rel.isBlank()) return null
        return joinUpdateUrl(resolveUpdateDownloadBase(input), rel)
    }

    fun isTunnelApiBase(base: String): Boolean {
        if (base.isBlank()) return false
        if (base.contains(WG_TUNNEL_GATEWAY)) return true
        if (base.contains("127.0.0.1") && base.contains(":9000")) return true
        return base.startsWith("http://") &&
            base.substringAfter("http://").substringBefore('/').substringBefore(':')
                .matches(Regex("""\d+\.\d+\.\d+\.\d+"""))
    }
}
