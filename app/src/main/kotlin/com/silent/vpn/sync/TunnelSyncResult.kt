package com.silent.vpn.sync

/** Детальный результат post-connect sync — для логов и UI. */
data class TunnelSyncResult(
    val ok: Boolean = false,
    val connectOk: Boolean = false,
    val connectHttpCode: Int = 0,
    val subscriptionDenied: Boolean = false,
    val hashesOk: Boolean = false,
    val profileOk: Boolean = false,
    val apiUrl: String = "",
    val proxyActive: Boolean = false,
    val mobile: Boolean = false,
    val excludedApp: Boolean = false,
    val error: String? = null,
) {
    fun logSummary(step: String = "syncAll") {
        MobileSyncLog.i(
            step,
            "ok=$ok connect=$connectOk code=$connectHttpCode denied=$subscriptionDenied " +
                "hashes=$hashesOk profile=$profileOk " +
                "mobile=$mobile excluded=$excludedApp proxy=$proxyActive url=$apiUrl" +
                (error?.let { " err=$it" } ?: ""),
        )
    }
}
