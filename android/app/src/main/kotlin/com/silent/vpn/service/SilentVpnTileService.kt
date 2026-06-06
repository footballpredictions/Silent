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
import com.silent.vpn.vpn.WdttTunnelManager

@RequiresApi(Build.VERSION_CODES.N)
class SilentVpnTileService : TileService() {

    override fun onStartListening() {
        refreshTile()
    }

    override fun onClick() {
        if (isLocked) {
            unlockAndRun { performClick() }
        } else {
            performClick()
        }
    }

    private fun performClick() {
        if (VpnTileConnect.isVpnActive()) {
            VpnTileConnect.disconnect(this)
        } else {
            when (VpnTileConnect.tryConnect(this)) {
                VpnTileConnect.ConnectResult.Started -> Unit
                VpnTileConnect.ConnectResult.NeedVpnPermission ->
                    collapseToActivity(TileConnectActivity.intent(this))
                VpnTileConnect.ConnectResult.NeedLogin,
                VpnTileConnect.ConnectResult.NoConfig,
                -> collapseToActivity(MainActivity.openIntent(this))
                VpnTileConnect.ConnectResult.AlreadyConnected -> Unit
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
        val tile = qsTile ?: return
        val connected = SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value
        val connecting = SilentVpnService.isRunning && !connected

        tile.icon = Icon.createWithResource(this, R.drawable.ic_tile_silent)
        tile.label = getString(R.string.app_name)
        when {
            connected -> {
                tile.state = Tile.STATE_ACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_connected)
            }
            connecting -> {
                tile.state = Tile.STATE_ACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_connecting)
            }
            else -> {
                tile.state = Tile.STATE_INACTIVE
                tile.subtitle = getString(R.string.tile_subtitle_disconnected)
            }
        }
        tile.updateTile()
    }
}
