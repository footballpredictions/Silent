package com.silent.vpn

import android.content.Intent
import android.net.Uri
import android.net.VpnService
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.runtime.*
import com.silent.vpn.ui.screens.LoginScreen
import com.silent.vpn.ui.screens.MainScreen
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.ui.theme.SilentTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    private val vm: MainViewModel by viewModels()
    private var vpnPermissionGranted = mutableStateOf(false)

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) vpnPermissionGranted.value = true
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        handleVkDeepLink(intent)

        setContent {
            val screen by vm.screen.collectAsState()
            val profile by vm.profile.collectAsState()
            val vpnState by vm.vpnState.collectAsState()
            val theme by vm.theme.collectAsState()
            val authLoading by vm.authLoading.collectAsState()
            val authError by vm.authError.collectAsState()
            val vpnError by vm.vpnError.collectAsState()
            val regDone by vm.regDone.collectAsState()
            val regEmail by vm.regEmail.collectAsState()
            val vkReady by vm.vkReady.collectAsState()
            val vkUserId by vm.vkUserId.collectAsState()
            val bootstrapHash by vm.bootstrapHash.collectAsState()
            val vkMsg by vm.vkMsg.collectAsState()

            LaunchedEffect(vpnPermissionGranted.value) {
                if (vpnPermissionGranted.value) {
                    vpnPermissionGranted.value = false
                    vm.connect(this@MainActivity)
                }
            }

            SilentTheme(themeData = theme) {
                when (screen) {
                    AppScreen.LOGIN -> LoginScreen(
                        onLogin = vm::login,
                        onRegister = vm::register,
                        loading = authLoading,
                        error = authError,
                        regDone = regDone,
                        regEmail = regEmail,
                        vkReady = vkReady,
                        vkUserId = vkUserId,
                        bootstrapHash = bootstrapHash,
                        vkMsg = vkMsg,
                        onLinkVk = {
                            vm.linkVkGuest { url ->
                                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                            }
                        },
                        onClearError = vm::clearAuthError,
                        onRegDoneDismiss = vm::dismissRegDone,
                    )
                    AppScreen.MAIN -> MainScreen(
                        profile = profile,
                        vpnState = vpnState,
                        theme = theme,
                        vpnError = vpnError,
                        onToggle = {
                            if (vpnState == VpnState.DISCONNECTED) {
                                val intent = VpnService.prepare(this@MainActivity)
                                if (intent != null) vpnPermissionLauncher.launch(intent)
                                else vm.connect(this@MainActivity)
                            } else if (vpnState == VpnState.CONNECTED) {
                                vm.disconnect(this@MainActivity)
                            }
                        },
                        onLogout = { vm.logout(this@MainActivity) },
                        onClearVpnError = vm::clearVpnError,
                        onCheckPromo = vm::checkPromo,
                        onInitPayment = vm::initPayment,
                        onOpenUrl = { url ->
                            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        },
                        onShowError = vm::showError,
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleVkDeepLink(intent)
    }

    private fun handleVkDeepLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "silentvpn" || data.host != "vk-linked") return
        vm.handleVkDeepLink(data.getQueryParameter("boot"), data.getQueryParameter("vk")?.toLongOrNull())
    }
}
