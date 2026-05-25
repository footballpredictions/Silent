package com.silent.vpn

import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.*
import androidx.lifecycle.viewmodel.compose.viewModel
import com.silent.vpn.ui.screens.MainScreen
import com.silent.vpn.ui.screens.SideMenuContent
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.ui.theme.SilentTheme
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            // VPN permission granted — trigger connect again
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            val vm: MainViewModel = viewModel()
            val profile by vm.profile.collectAsState()
            val vpnState by vm.vpnState.collectAsState()
            val theme by vm.theme.collectAsState()
            val drawerState = rememberDrawerState(DrawerValue.Closed)
            val scope = rememberCoroutineScope()

            SilentTheme(themeData = theme) {
                ModalNavigationDrawer(
                    drawerState = drawerState,
                    gesturesEnabled = true,
                    drawerContent = {
                        SideMenuContent(
                            profile = profile,
                            theme = theme,
                            onClose = { scope.launch { drawerState.close() } },
                            onSubscription = { scope.launch { drawerState.close() }; vm.openSubscription() },
                            onSettings = { scope.launch { drawerState.close() } },
                            onPromo = { scope.launch { drawerState.close() } },
                            onDevices = { scope.launch { drawerState.close() } },
                            onSupport = { scope.launch { drawerState.close() } },
                            onAbout = { scope.launch { drawerState.close() } },
                            onLogout = { scope.launch { drawerState.close() }; vm.logout() },
                        )
                    }
                ) {
                    MainScreen(
                        profile = profile,
                        vpnState = vpnState,
                        theme = theme,
                        onToggle = {
                            if (vpnState == VpnState.DISCONNECTED) {
                                val intent = VpnService.prepare(this@MainActivity)
                                if (intent != null) {
                                    vpnPermissionLauncher.launch(intent)
                                } else {
                                    vm.connect(this@MainActivity)
                                }
                            } else if (vpnState == VpnState.CONNECTED) {
                                vm.disconnect(this@MainActivity)
                            }
                        },
                        onMenuClick = { scope.launch { drawerState.open() } },
                    )
                }
            }
        }
    }
}
