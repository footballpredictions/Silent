package com.silent.vpn.data

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class QrLoginPayload(
    val kind: String,
    val code: String,
) {
    fun toUri(): String = buildQrPayload(kind, code)

    val isSession: Boolean get() = kind == KIND_SESSION
    val isUser: Boolean get() = kind == KIND_USER

    companion object {
        const val KIND_SESSION = "s"
        const val KIND_USER = "u"
        const val PREFIX = "silentvpn://qr"
    }
}

fun buildQrPayload(kind: String, code: String): String {
    val encoded = URLEncoder.encode(code, StandardCharsets.UTF_8).replace("+", "%20")
    return "${QrLoginPayload.PREFIX}?k=$kind&c=$encoded"
}

fun parseQrPayload(raw: String?): QrLoginPayload? {
    val text = raw?.trim().orEmpty()
    if (text.isEmpty()) return null
    val silentIdx = text.indexOf(QrLoginPayload.PREFIX, ignoreCase = true)
    val httpsMatch = HTTPS_QR.find(text)
    val sliced = when {
        silentIdx >= 0 -> text.substring(silentIdx).trim()
        httpsMatch != null -> text.substring(httpsMatch.range.first).trim()
        else -> text
    }
    val uri = sliced.split(Regex("\\s+"), limit = 2).first()
    val query = when {
        uri.startsWith(QrLoginPayload.PREFIX, ignoreCase = true) ->
            uri.substringAfter('?', missingDelimiterValue = "")
        HTTPS_QR.containsMatchIn(uri) ->
            uri.substringAfter('?', missingDelimiterValue = "")
        else -> return null
    }
    if (query.isEmpty()) return null
    var kind = ""
    var code = ""
    for (part in query.split('&')) {
        val key = part.substringBefore('=')
        val value = part.substringAfter('=', missingDelimiterValue = "")
        if (key == "k") kind = URLDecoder.decode(value, StandardCharsets.UTF_8).trim()
        if (key == "c") code = URLDecoder.decode(value, StandardCharsets.UTF_8).trim()
    }
    if (kind != QrLoginPayload.KIND_SESSION && kind != QrLoginPayload.KIND_USER) return null
    if (!code.matches(Regex("^[A-Za-z0-9_-]{8,128}$"))) return null
    return QrLoginPayload(kind, code)
}

private val HTTPS_QR = Regex("https?://\\S+/qr\\?", RegexOption.IGNORE_CASE)

/** Рабочий main VPN не рвём: временный bootstrap только если туннеля нет. */
fun qrApproveKeepsExistingVpn(
    mainVpnUp: Boolean,
    serviceRunning: Boolean,
    bootstrapMode: Boolean,
): Boolean = mainVpnUp || (serviceRunning && !bootstrapMode)

/** Не пересоздавать QR на ТВ, пока код жив — иначе телефон подтверждает уже брошенную сессию. */
fun shouldReuseQrWaitingSession(
    forceRefresh: Boolean,
    token: String,
    payload: String,
    expired: Boolean,
): Boolean = !forceRefresh && !expired && token.isNotBlank() && payload.isNotBlank()

sealed class QrPollDecision {
    data class Approved(val access: String, val refresh: String) : QrPollDecision()
    data object Pending : QrPollDecision()
    data object Expired : QrPollDecision()
    data class Failed(val message: String) : QrPollDecision()
    data object Retry : QrPollDecision()
}

/**
 * Разбор poll: 403/4xx после confirm нельзя крутить как «нет связи» —
 * телефон уже approved, ТВ должен показать ошибку или войти.
 */
fun interpretQrPoll(
    httpCode: Int,
    status: String?,
    accessToken: String?,
    refreshToken: String?,
    errorText: String?,
): QrPollDecision {
    if (httpCode in 200..299) {
        return when (status) {
            "approved" -> {
                if (!accessToken.isNullOrBlank() && !refreshToken.isNullOrBlank()) {
                    QrPollDecision.Approved(accessToken, refreshToken)
                } else {
                    QrPollDecision.Failed(
                        errorText?.ifBlank { null } ?: "Сервер подтвердил QR, но не выдал вход",
                    )
                }
            }
            "expired" -> QrPollDecision.Expired
            else -> QrPollDecision.Pending
        }
    }
    if (httpCode in 400..499 && httpCode != 408 && httpCode != 429) {
        return QrPollDecision.Failed(errorText?.ifBlank { null } ?: "Ошибка входа ($httpCode)")
    }
    return QrPollDecision.Retry
}
