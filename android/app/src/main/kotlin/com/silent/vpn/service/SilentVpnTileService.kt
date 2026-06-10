package com.silent.vpn.service

import android.app.PendingIntent
import android.content.Intent
import android.graphics.drawable.Icon
import android.net.VpnService
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import android.util.Log
import android.widget.Toast
import androidx.annotation.RequiresApi
import com.silent.vpn.MainActivity
import com.silent.vpn.R
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Quick Settings — как reference: [WdttTunnelManager.running] + [SilentVpnService.isRunning].
 * После kill с VPN ON: OS может кешировать ACTIVE — принудительно синхронизируем.
 */
@RequiresApi(Build.VERSION_CODES.N)
class SilentVpnTileService : TileService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var stateJob: Job? = null

    override fun onStartListening() {
        super.onStartListening()
        VpnServiceTracker.reconcileStaleSession(this)
        updateTile(isVpnConnected())
        stateJob?.cancel()
        stateJob = scope.launch {
            try {
                WdttTunnelManager.running.collect {
                    updateTile(isVpnConnected())
                }
            } catch (e: Exception) {
                Log.e(TAG, "running collect failed", e)
            }
        }
    }

    override fun onStopListening() {
        stateJob?.cancel()
        super.onStopListening()
    }

    override fun onClick() {
        super.onClick()
        if (isLocked) {
            unlockAndRun { performClick() }
        } else {
            performClick()
        }
    }

    private fun isVpnConnected(): Boolean =
        WdttTunnelManager.running.value && SilentVpnService.isRunning

    private fun performClick() {
        runCatching {
            VpnServiceTracker.reconcileStaleSession(this)

            if (VpnTileConnect.isCaptchaPending()) {
                ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
                return
            }

            val connected = isVpnConnected()
            // Залипшая ACTIVE после kill с VPN ON — синхронизируем до действия.
            if (!connected) {
                updateTile(false)
            }

            if (connected) {
                startService(
                    Intent(this, SilentVpnService::class.java).apply {
                        action = SilentVpnService.ACTION_DISCONNECT
                    },
                )
                return
            }

            if (VpnService.prepare(this) != null) {
                Toast.makeText(
                    this,
                    "Откройте Silent VPN и выдайте VPN-разрешение",
                    Toast.LENGTH_LONG,
                ).show()
                openMainActivity()
                return
            }

            scope.launch {
                try {
                    withContext(Dispatchers.IO) {
                        VpnConnectHelper.ensureCleanSlate(this@SilentVpnTileService)
                    }
                    val intent = VpnTileConnect.buildConnectIntentFromCache(this@SilentVpnTileService)
                    if (intent == null) {
                        Toast.makeText(
                            this@SilentVpnTileService,
                            "Откройте Silent VPN и войдите в аккаунт",
                            Toast.LENGTH_LONG,
                        ).show()
                        openMainActivity()
                        return@launch
                    }
                    startForegroundService(intent)
                } catch (e: Exception) {
                    Log.e(TAG, "start via tile failed", e)
                    Toast.makeText(
                        this@SilentVpnTileService,
                        "Ошибка запуска: ${e.localizedMessage}",
                        Toast.LENGTH_SHORT,
                    ).show()
                }
            }
        }.onFailure { e ->
            Log.e(TAG, "onClick failed", e)
        }
    }

    private fun updateTile(connected: Boolean) {
        runCatching {
            qsTile?.apply {
                label = getString(R.string.app_name)
                icon = Icon.createWithResource(this@SilentVpnTileService, R.drawable.ic_tile_silent)
                when {
                    VpnTileConnect.isCaptchaPending() -> {
                        state = Tile.STATE_ACTIVE
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            subtitle = getString(R.string.tile_subtitle_captcha)
                        }
                    }
                    connected -> {
                        state = Tile.STATE_ACTIVE
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            subtitle = getString(R.string.tile_subtitle_connected)
                        }
                    }
                    else -> {
                        state = Tile.STATE_INACTIVE
                        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                            subtitle = getString(R.string.tile_subtitle_disconnected)
                        }
                    }
                }
                updateTile()
            }
        }.onFailure { e ->
            Log.e(TAG, "updateTile failed", e)
        }
    }

    private fun openMainActivity() {
        runCatching {
            val intent = MainActivity.openIntent(this)
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
        }.onFailure { e ->
            Log.e(TAG, "openMainActivity failed", e)
        }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private companion object {
        const val TAG = "SilentVpnTile"
    }
}
