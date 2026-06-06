package com.silent.vpn.service

import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import com.silent.vpn.MainActivity

/**
 * Прозрачная активность: только запрос VPN-разрешения для плитки QS.
 * Не открывает UI приложения — сразу закрывается после старта VPN.
 */
class TileConnectActivity : ComponentActivity() {

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            VpnTileConnect.connectAfterPermission(this)
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        when (VpnTileConnect.tryConnect(this)) {
            VpnTileConnect.ConnectResult.Started,
            VpnTileConnect.ConnectResult.AlreadyConnected,
            -> finish()
            VpnTileConnect.ConnectResult.NeedVpnPermission -> {
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
