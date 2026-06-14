package com.silent.vpn

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.core.content.ContextCompat
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
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.vk.VkCallsLink
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    companion object {
        @Volatile
        var isForeground: Boolean = false

        const val EXTRA_OPEN_MAIN = "open_main"
        const val EXTRA_TILE_CONNECT = "tile_connect"

        fun openIntent(context: Context): Intent =
            Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_NEW_TASK
                putExtra(EXTRA_OPEN_MAIN, true)
            }

        fun tileConnectIntent(context: Context): Intent =
            openIntent(context).apply { putExtra(EXTRA_TILE_CONNECT, true) }
    }

    private val vm: MainViewModel by viewModels()
    private var vpnPermissionGranted = mutableStateOf(false)
    private var pendingBootstrapAfterPermission = mutableStateOf(false)
    private var pendingHashInput = mutableStateOf("")

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* optional — FGS notification still works */ }

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

    private val installUpdateLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { /* системный установщик APK */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        SessionTrace.mark("MainActivity.onCreate", BuildConfig.VERSION_NAME)
        DebugLog.i("App", "Silent VPN ${android.os.Build.MODEL} API ${android.os.Build.VERSION.SDK_INT}")

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

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
            val bootstrapReady by vm.bootstrapReady.collectAsState()
            val bootstrapSecondsLeft by vm.bootstrapSecondsLeft.collectAsState()
            val sessionDeviceId by vm.sessionDeviceId.collectAsState()
            val updateInfo by vm.updateInfo.collectAsState()
            val updateProgress by vm.updateProgress.collectAsState()
            val updateDownloading by vm.updateDownloading.collectAsState()
            val forgotSent by vm.forgotSent.collectAsState()

            LaunchedEffect(Unit) {
                handleTileConnectIntent(intent)
            }

            LaunchedEffect(vpnPermissionGranted.value) {
                if (vpnPermissionGranted.value) {
                    vpnPermissionGranted.value = false
                    vm.connect(this@MainActivity)
                }
            }

            LaunchedEffect(screen) {
                if (screen == AppScreen.LOGIN) {
                    vm.reconcileLoginBootstrapSession(this@MainActivity)
                }
            }

            SilentTheme(themeData = theme) {
                when (screen) {
                    AppScreen.LOGIN -> LoginScreen(
                        theme = theme,
                        initialEmail = vm.lastEmail,
                        initialRememberMe = vm.rememberMe,
                        forgotSent = forgotSent,
                        onLogin = { email, password, remember -> vm.login(email, password, remember, this@MainActivity) },
                        onRegister = vm::register,
                        onForgotPassword = vm::forgotPassword,
                        onClearForgotSent = vm::clearForgotSent,
                        loading = authLoading,
                        error = authError,
                        regDone = regDone,
                        regEmail = regEmail,
                        bootstrapHash = bootstrapHash,
                        statusMsg = statusMsg,
                        bootstrapConnecting = bootstrapConnecting,
                        bootstrapReady = bootstrapReady,
                        bootstrapSecondsLeft = bootstrapSecondsLeft,
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
                        onOpenVkLink = { url ->
                            VkCallsLink.openCalls(this@MainActivity, url)
                        },
                        onClearError = vm::clearAuthError,
                        onRegDoneDismiss = vm::dismissRegDone,
                        onSyncBootstrap = { vm.reconcileLoginBootstrapSession(this@MainActivity) },
                    )
                    AppScreen.MAIN -> MainScreen(
                        profile = profile,
                        vpnState = vpnState,
                        theme = theme,
                        repo = vm.repository,
                        sessionDeviceId = sessionDeviceId,
                        vpnError = vpnError,
                        onToggle = {
                            when (vpnState) {
                                VpnState.DISCONNECTED -> {
                                    val intent = VpnService.prepare(this@MainActivity)
                                    if (intent != null) vpnPermissionLauncher.launch(intent)
                                    else vm.connect(this@MainActivity)
                                }
                                VpnState.CONNECTED, VpnState.DISCONNECTING ->
                                    vm.disconnect(this@MainActivity)
                                VpnState.CONNECTING -> { /* reference: не рвём connect повторным toggle */ }
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
                        onDevicesScreenActive = vm::setSessionsScreenActive,
                        onVpnProfilePolling = vm::setVpnProfilePolling,
                        updateInfo = updateInfo,
                        updateDownloading = updateDownloading,
                        updateProgress = updateProgress,
                        onUpdateClick = {
                            vm.downloadAndInstallUpdate(this@MainActivity) { intent ->
                                installUpdateLauncher.launch(intent)
                            }
                        },
                        onUpdatePolling = vm::setUpdatePolling,
                    )
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getBooleanExtra(EXTRA_OPEN_MAIN, false)) {
            vm.onReturnedToApp()
        }
        handleTileConnectIntent(intent)
    }

    private fun handleTileConnectIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_TILE_CONNECT, false) != true) return
        intent.removeExtra(EXTRA_TILE_CONNECT)

        if (SilentVpnService.isRunning) return
        if (!vm.repository.isLoggedIn()) return

        val prep = VpnService.prepare(this)
        if (prep != null) vpnPermissionLauncher.launch(prep)
        else vpnPermissionGranted.value = true
    }

    override fun onResume() {
        super.onResume()
        isForeground = true
        SessionTrace.mark("MainActivity.onResume")
        vm.onAppResumed()
        ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
    }

    override fun onPause() {
        isForeground = false
        SessionTrace.mark("MainActivity.onPause")
        super.onPause()
    }
}
