package com.silent.vpn.vpn

/** Decisions made by the Android host from native authentication logs. */
internal object VkAuthLogPolicy {
    private val internalErrorCode = Regex("""\berror_code["']?\s*[:=]\s*10\b""", RegexOption.IGNORE_CASE)

    fun isTemporaryApiFailure(message: String): Boolean {
        val m = message.lowercase()
        if (m.contains("call not found") || m.contains("invalid join link") ||
            m.contains("join link is not valid") || m.contains("conversation not found")) return false
        return internalErrorCode.containsMatchIn(m) || (m.contains("error 10") && m.contains("internal"))
    }

    fun shouldEscalateFromLog(message: String): Boolean {
        if (isTemporaryApiFailure(message)) return false
        val m = message.lowercase()
        return m.contains("legacy_escalate_captcha") || m.contains("flood_escalate_captcha") ||
            m.contains("flood control") || m.contains("kind=flood")
    }

    fun cleanHashPrefix(prefix: String): String = prefix.trimEnd('.', ')', '…')

    fun resolveGroupHash(groupId: Int, prefix: String?, hashes: List<String>): String? {
        if (prefix != null) {
            return hashes.filter { it.startsWith(prefix) }.singleOrNull()
        }
        if (hashes.isEmpty()) return null
        return hashes[(groupId - 1).coerceAtLeast(0) % hashes.size]
    }
}
