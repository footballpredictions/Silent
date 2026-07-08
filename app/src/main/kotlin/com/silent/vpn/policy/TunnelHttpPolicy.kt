package com.silent.vpn.policy

import retrofit2.Response

object TunnelHttpPolicy {

    fun isTunnelBackendFailure(httpCode: Int): Boolean = httpCode == 502 || httpCode == 503

    fun isTunnelBackendFailure(response: Response<*>?): Boolean =
        response != null && isTunnelBackendFailure(response.code())

    fun isTunnelUpstreamError(message: String?): Boolean {
        val m = message?.lowercase().orEmpty()
        return m.contains("upstream failed") ||
            m.contains("vpn upstream") ||
            m.contains("upstream error") ||
            m.contains("tunnel backend unavailable")
    }
}
