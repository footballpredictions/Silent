package com.silent.vpn.service

import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.service.quicksettings.TileService
import com.silent.vpn.util.SessionTrace
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

object VpnTileHelper {
    /** Не дёргать QS чаще — иначе шум в logcat и лишние bind/unbind плитки. */
    private const val MIN_REQUEST_INTERVAL_MS = 2_500L

    private val changes = MutableStateFlow(0L)
    internal val stateChanges = changes.asStateFlow()

    private val lock = Any()
    private val mainHandler by lazy { Handler(Looper.getMainLooper()) }
    private var lastRequestMs: Long? = null
    private var pendingContext: Context? = null
    private var requestScheduled = false
    private val pendingRequest = Runnable {
        val context = synchronized(lock) {
            requestScheduled = false
            pendingContext?.also {
                pendingContext = null
                lastRequestMs = SystemClock.elapsedRealtime()
            }
        }
        context?.let(::requestListening)
    }

    fun requestUpdate(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
        // A currently bound tile sees service/captcha changes even if no ready flow changed.
        changes.update { it + 1L }
        val appContext = context.applicationContext
        val now = SystemClock.elapsedRealtime()
        val immediate = synchronized(lock) {
            val last = lastRequestMs
            if (last == null || now - last >= MIN_REQUEST_INTERVAL_MS) {
                mainHandler.removeCallbacks(pendingRequest)
                pendingContext = null
                requestScheduled = false
                lastRequestMs = now
                true
            } else {
                // Keep one trailing refresh: CONNECT/ready/DISCONNECT can all occur
                // inside the interval while an ACTIVE_TILE is not bound by System UI.
                pendingContext = appContext
                if (!requestScheduled) {
                    requestScheduled = true
                    mainHandler.postDelayed(pendingRequest, MIN_REQUEST_INTERVAL_MS - (now - last))
                }
                false
            }
        }
        if (immediate) requestListening(appContext)
    }

    private fun requestListening(context: Context) {
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
