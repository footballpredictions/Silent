package com.silent.vpn.policy

/**
 * Debug (`com.silent.vpn.debug`) и release (`com.silent.vpn`) — два UID.
 * После свайпа из недавних чужой пакет часто оставляет зомби-VPN: наша иконка
 * не поднимается, пока OEM не сбросит сеть (airplane) или ребут.
 */
object SiblingVpnPolicy {
    const val RELEASE_PACKAGE = "com.silent.vpn"
    const val DEBUG_PACKAGE = "com.silent.vpn.debug"
    const val ACTION_SIBLING_TEARDOWN = "com.silent.vpn.action.SIBLING_TEARDOWN"

    /** Ждём, пока чужой TUN исчезнет после teardown / revoke. */
    const val FOREIGN_VPN_WAIT_MS = 8_000L
    const val FOREIGN_VPN_POLL_MS = 250L

    fun isSilentFamilyPackage(packageName: String): Boolean {
        val p = packageName.trim()
        return p == RELEASE_PACKAGE || p == DEBUG_PACKAGE
    }

    fun siblingPackage(ourPackage: String): String? = when (ourPackage.trim()) {
        RELEASE_PACKAGE -> DEBUG_PACKAGE
        DEBUG_PACKAGE -> RELEASE_PACKAGE
        else -> null
    }

    /**
     * Просим sibling снять свой VPN перед нашим establish.
     * Даже если «чужой VPN» — NordVPN и т.п., пустой broadcast sibling’у безвреден;
     * имеет смысл только если sibling установлен.
     */
    fun shouldRequestSiblingTeardown(
        ourPackage: String,
        siblingInstalled: Boolean,
        otherVpnActive: Boolean,
    ): Boolean {
        if (!otherVpnActive || !siblingInstalled) return false
        return siblingPackage(ourPackage) != null
    }

    /** Имя WG-туннеля разное у debug/release — меньше путаницы в логах/состоянии GoBackend. */
    fun wgTunnelName(packageName: String): String =
        if (packageName.trim().endsWith(".debug")) "silent_dbg" else "silent"

    fun foreignVpnWaitAttempts(
        waitMs: Long = FOREIGN_VPN_WAIT_MS,
        pollMs: Long = FOREIGN_VPN_POLL_MS,
    ): Int {
        if (waitMs <= 0L || pollMs <= 0L) return 1
        return ((waitMs + pollMs - 1) / pollMs).toInt().coerceAtLeast(1)
    }

    /**
     * После смены debug↔release: если чужой VPN ещё жив — не считаем «чистый» старт,
     * нужен teardown + полный WG reset.
     */
    fun needsForeignVpnCleanup(otherVpnActive: Boolean): Boolean = otherVpnActive
}
