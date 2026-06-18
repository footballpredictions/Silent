package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.silent.vpn.MainActivity
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.launch

/** Запрос VPN-разрешения для плитки (если пользователь открыл приложение вручную). */
class TileConnectActivity : ComponentActivity() {

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        SessionTrace.mark("TileConnectActivity.vpnPermission", "result=${result.resultCode}")
        if (result.resultCode == RESULT_OK) {
            lifecycleScope.launch {
                VpnTileConnect.buildConnectIntentFromCache(this@TileConnectActivity)?.let { intent ->
                    ContextCompat.startForegroundService(this@TileConnectActivity, intent)
                }
            }
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SessionTrace.enter("TileConnectActivity.onCreate")
        if (SilentVpnService.isRunning || WdttTunnelManager.running.value) {
            SessionTrace.exit("TileConnectActivity.onCreate", "already running")
            finish()
            return
        }
        val prep = VpnService.prepare(this)
        if (prep != null) {
            vpnPermissionLauncher.launch(prep)
        } else {
            lifecycleScope.launch {
                val intent = VpnTileConnect.buildConnectIntentFromCache(this@TileConnectActivity)
                if (intent != null) {
                    ContextCompat.startForegroundService(this@TileConnectActivity, intent)
                } else {
                    startActivity(MainActivity.openIntent(this@TileConnectActivity))
                }
                finish()
            }
        }
    }

    companion object {
        fun intent(context: Context): Intent =
            Intent(context, TileConnectActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            }
    }
}
