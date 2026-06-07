package com.silent.vpn.service

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import androidx.annotation.RequiresApi
import com.silent.vpn.MainActivity
import com.silent.vpn.R
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager

@RequiresApi(Build.VERSION_CODES.N)
class SilentVpnTileService : TileService() {

    override fun onStartListening() {
        SessionTrace.enter("SilentVpnTileService.onStartListening")
        VpnServiceTracker.reconcileStaleSession(applicationContext)
        refreshTile()
        SessionTrace.exit("SilentVpnTileService.onStartListening")
    }

    override fun onStopListening() {
        SessionTrace.mark("SilentVpnTileService.onStopListening")
        refreshTile()
    }

    override fun onClick() {
        SessionTrace.enter("SilentVpnTileService.onClick", "locked=$isLocked")
        if (isLocked) {
            unlockAndRun { performClick() }
        } else {
            performClick()
        }
        SessionTrace.exit("SilentVpnTileService.onClick")
    }

    private fun performClick() {
        when {
            VpnTileConnect.isCaptchaPending() -> {
                SessionTrace.mark("SilentVpnTileService.performClick", "captcha")
                ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
            }
            VpnTileConnect.canDisconnectFromTile(this) -> {
                SessionTrace.mark("SilentVpnTileService.performClick", "disconnect")
                VpnTileConnect.disconnect(this)
            }
            else -> when (VpnTileConnect.tryConnect(this)) {
                VpnTileConnect.ConnectResult.Started ->
                    SessionTrace.mark("SilentVpnTileService.performClick", "connect started")
                VpnTileConnect.ConnectResult.NeedVpnPermission -> {
                    SessionTrace.mark("SilentVpnTileService.performClick", "need permission")
                    collapseToActivity(TileConnectActivity.intent(this))
                }
                VpnTileConnect.ConnectResult.NeedLogin,
                VpnTileConnect.ConnectResult.NoConfig,
                -> {
                    SessionTrace.mark("SilentVpnTileService.performClick", "open app")
                    collapseToActivity(MainActivity.openIntent(this))
                }
                VpnTileConnect.ConnectResult.AlreadyConnected ->
                    SessionTrace.mark("SilentVpnTileService.performClick", "already connected")
                VpnTileConnect.ConnectResult.Busy ->
                    SessionTrace.mark("SilentVpnTileService.performClick", "busy result")
            }
        }
        refreshTile()
    }

    private fun collapseToActivity(intent: Intent) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startActivityAndCollapse(
                PendingIntent.getActivity(
                    this,
                    0,
                    intent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                ),
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }

    private fun refreshTile() {
        val tile = qsTile ?: run {
            SessionTrace.mark("SilentVpnTileService.refreshTile", "qsTile=null")
            return
        }
        val connected = VpnTileConnect.isVpnActive(this)
        val busy = VpnTileConnect.isSessionBusy(this)
        val connecting = busy && !connected
        val captcha = VpnTileConnect.isCaptchaPending()

        tile.icon = Icon.createWithResource(this, R.drawable.ic_tile_silent)
        tile.label = getString(R.string.app_name)
        val subtitleKey = when {
            captcha -> {
                tile.state = Tile.STATE_ACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_captcha)
                "captcha"
            }
            connected -> {
                tile.state = Tile.STATE_ACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_connected)
                "connected"
            }
            connecting -> {
                tile.state = Tile.STATE_ACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_connecting)
                "connecting"
            }
            else -> {
                tile.state = Tile.STATE_INACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_disconnected)
                "disconnected"
            }
        }
        tile.updateTile()
        SessionTrace.mark(
            "SilentVpnTileService.refreshTile",
            "state=$subtitleKey tileState=${tile.state} connected=$connected busy=$busy",
        )
    }
}
