package com.silent.vpn.service

import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.service.quicksettings.TileService

object VpnTileHelper {
    fun requestUpdate(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.N) return
        runCatching {
            TileService.requestListeningState(
                context,
                ComponentName(context, SilentVpnTileService::class.java),
            )
        }
    }
}
