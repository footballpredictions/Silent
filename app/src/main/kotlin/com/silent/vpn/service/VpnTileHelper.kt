package com.silent.vpn.service

import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.service.quicksettings.TileService
import com.silent.vpn.util.SessionTrace

object VpnTileHelper {
    /** Не дёргать QS чаще — иначе шум в logcat и лишние bind/unbind плитки. */
    private const val MIN_REQUEST_INTERVAL_MS = 2_500L

    @Volatile
    private var lastRequestMs = 0L

    fun requestUpdate(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
        val now = System.currentTimeMillis()
        if (now - lastRequestMs < MIN_REQUEST_INTERVAL_MS) return
        lastRequestMs = now
        runCatching {
            TileService.requestListeningState(
                context.applicationContext,
                ComponentName(context.applicationContext, SilentVpnTileService::class.java),
            )
        }.onFailure { e ->
            if (isBenignTileRequestError(e)) return@onFailure
            SessionTrace.warn("VpnTileHelper.requestUpdate", e.message ?: e.javaClass.simpleName)
        }
    }

    /** Плитка не в шторке / сервис ещё не привязан — не ошибка VPN. */
    private fun isBenignTileRequestError(e: Throwable): Boolean {
        val msg = e.message?.lowercase().orEmpty()
        return e is IllegalStateException ||
            e is IllegalArgumentException ||
            msg.contains("not available") ||
            msg.contains("not bound") ||
            msg.contains("not registered") ||
            msg.contains("unknown component")
    }
}
