package com.silent.vpn.vpn

/**
 * JNI wrapper for hev-socks5-tunnel (libhev-socks5-tunnel.so).
 * Все 4 метода обязательны — JNI_OnLoad RegisterNatives падает без любого из них.
 */
object HevSocksTunnel {
    @Volatile
    private var loaded = false

    fun isLoaded(): Boolean = loaded

    fun ensureLoaded(): Boolean {
        if (loaded) return true
        return try {
            System.loadLibrary("hev-socks5-tunnel")
            loaded = true
            true
        } catch (e: Throwable) {
            WdttTunnelManager.logUi(
                "hev_load",
                "libhev-socks5-tunnel.so: ${e.message}",
                99,
                isError = true,
            )
            false
        }
    }

    fun stopIfLoaded() {
        if (!loaded) return
        runCatching { TProxyStopService() }
    }

    @JvmStatic
    external fun TProxyStartService(configPath: String, fd: Int): Boolean

    @JvmStatic
    external fun TProxyStopService(): Boolean

    @JvmStatic
    external fun TProxyIsRunning(): Boolean

    @JvmStatic
    external fun TProxyGetStats(): LongArray
}
