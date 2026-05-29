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
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    companion object {
        @Volatile
        var isForeground: Boolean = false
    }

    private val vm: MainViewModel by viewModels()
    private var vpnPermissionGranted = mutableStateOf(false)
    private var pendingBootstrapAfterPermission = mutableStateOf(false)
    private var pendingHashInput = mutableStateOf("")

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            if (pendingBootstrapAfterPermission.value) {
                pendingBootstrapAfterPermission.value = false
                vm.connectForLogin(this, pendingHashInput.value)
            } else {
                vpnPermissionGranted.value = true
            }
        } else {
            pendingBootstrapAfterPermission.value = false
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        DebugLog.i("App", "Silent VPN ${android.os.Build.MODEL} API ${android.os.Build.VERSION.SDK_INT}")

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
            val bootstrapHash by vm.bootstrapHash.collectAsState()
            val statusMsg by vm.statusMsg.collectAsState()
            val bootstrapConnecting by vm.bootstrapConnecting.collectAsState()
            val sessionDeviceId by vm.sessionDeviceId.collectAsState()

            LaunchedEffect(vpnPermissionGranted.value) {
                if (vpnPermissionGranted.value) {
                    vpnPermissionGranted.value = false
                    vm.connect(this@MainActivity)
                }
            }

            SilentTheme(themeData = theme) {
                when (screen) {
                    AppScreen.LOGIN -> LoginScreen(
                        initialEmail = vm.lastEmail,
                        onLogin = { email, password -> vm.login(email, password, this@MainActivity) },
                        onRegister = vm::register,
                        loading = authLoading,
                        error = authError,
                        regDone = regDone,
                        regEmail = regEmail,
                        hashReady = !bootstrapHash.isNullOrBlank(),
                        bootstrapHash = bootstrapHash,
                        statusMsg = statusMsg,
                        bootstrapConnecting = bootstrapConnecting,
                        bootstrapReady = vpnState == VpnState.CONNECTED,
                        onConnect = { raw ->
                            val prep = VpnService.prepare(this@MainActivity)
                            pendingHashInput.value = raw
                            if (prep != null) {
                                pendingBootstrapAfterPermission.value = true
                                vpnPermissionLauncher.launch(prep)
                            } else {
                                vm.connectForLogin(this@MainActivity, raw)
                            }
                        },
                        onClearError = vm::clearAuthError,
                        onRegDoneDismiss = vm::dismissRegDone,
                    )
                    AppScreen.MAIN -> MainScreen(
                        profile = profile,
                        vpnState = vpnState,
                        theme = theme,
                        repo = vm.repository,
                        sessionDeviceId = sessionDeviceId,
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
                        onRenameDevice = vm::renameDevice,
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        isForeground = true
        ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
    }

    override fun onPause() {
        isForeground = false
        super.onPause()
    }
}
