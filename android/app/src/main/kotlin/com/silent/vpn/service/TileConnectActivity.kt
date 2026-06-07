package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.silent.vpn.MainActivity
import com.silent.vpn.util.SessionTrace

/**
 * Прозрачная активность: только запрос VPN-разрешения для плитки QS.
 * Не открывает UI приложения — сразу закрывается после старта VPN.
 */
class TileConnectActivity : ComponentActivity() {

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        SessionTrace.mark("TileConnectActivity.vpnPermission", "result=${result.resultCode}")
        if (result.resultCode == RESULT_OK) {
            VpnTileConnect.connectAfterPermission(this)
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        SessionTrace.enter("TileConnectActivity.onCreate")
        when (val r = VpnTileConnect.tryConnect(this)) {
            VpnTileConnect.ConnectResult.Started,
            VpnTileConnect.ConnectResult.AlreadyConnected,
            VpnTileConnect.ConnectResult.Busy,
            -> {
                SessionTrace.exit("TileConnectActivity.onCreate", r.name)
                finish()
            }
            VpnTileConnect.ConnectResult.NeedVpnPermission -> {
                SessionTrace.mark("TileConnectActivity.onCreate", "request permission")
                val prep = VpnService.prepare(this)
                if (prep != null) vpnPermissionLauncher.launch(prep)
                else {
                    VpnTileConnect.connectAfterPermission(this)
                    finish()
                }
            }
            VpnTileConnect.ConnectResult.NeedLogin,
            VpnTileConnect.ConnectResult.NoConfig,
            -> {
                SessionTrace.exit("TileConnectActivity.onCreate", "open app ${r.name}")
                startActivity(MainActivity.openIntent(this))
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
