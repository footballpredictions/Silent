package com.silent.vpn

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.provider.Settings
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
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra(EXTRA_OPEN_MAIN, true)
            }

        fun tileConnectIntent(context: Context): Intent =
            openIntent(context).apply { putExtra(EXTRA_TILE_CONNECT, true) }
    }

    private val vm: MainViewModel by viewModels()
    private var vpnPermissionGranted = mutableStateOf(false)
    private var pendingBootstrapAfterPermission = mutableStateOf(false)

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* optional — FGS notification still works */ }

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            if (pendingBootstrapAfterPermission.value) {
                pendingBootstrapAfterPermission.value = false
                vm.ensureBootstrapForAuthFlow(this)
            } else {
                vpnPermissionGranted.value = true
            }
        } else {
            pendingBootstrapAfterPermission.value = false
        }
    }

    private var pendingNotificationOpen = false
    private var pendingInstallIntent: Intent? = null

    private val installUpdateLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { /* системный установщик APK */ }
    private val unknownSourcesLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) {
        val installIntent = pendingInstallIntent ?: return@registerForActivityResult
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls()) {
            pendingInstallIntent = null
            installUpdateLauncher.launch(installIntent)
        } else {
            vm.showError("Разрешите установку из неизвестных источников для завершения обновления")
        }
    }

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

        pendingNotificationOpen = intent?.getBooleanExtra(EXTRA_OPEN_MAIN, false) == true
        if (pendingNotificationOpen) {
            intent?.removeExtra(EXTRA_OPEN_MAIN)
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
            val statusMsg by vm.statusMsg.collectAsState()
            val bootstrapConnecting by vm.bootstrapConnecting.collectAsState()
            val bootstrapReady by vm.bootstrapReady.collectAsState()
            val bootstrapSecondsLeft by vm.bootstrapSecondsLeft.collectAsState()
            val sessionDeviceId by vm.sessionDeviceId.collectAsState()
            val updateInfo by vm.updateInfo.collectAsState()
            val updateProgress by vm.updateProgress.collectAsState()
            val updateDownloading by vm.updateDownloading.collectAsState()
            val forgotSent by vm.forgotSent.collectAsState()
            val bootstrapExpired by vm.bootstrapExpired.collectAsState()

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
                if (screen != AppScreen.LOGIN) return@LaunchedEffect
                vm.reconcileLoginBootstrapSession(this@MainActivity)
                val prep = VpnService.prepare(this@MainActivity)
                if (prep != null) {
                    pendingBootstrapAfterPermission.value = true
                    vpnPermissionLauncher.launch(prep)
                } else {
                    vm.ensureBootstrapForAuthFlow(this@MainActivity)
                }
            }

            SilentTheme(themeData = theme) {
                when (screen) {
                    AppScreen.LOGIN -> LoginScreen(
                        theme = theme,
                        initialEmail = vm.lastEmail,
                        initialPassword = vm.lastPassword,
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
                        statusMsg = statusMsg,
                        bootstrapConnecting = bootstrapConnecting,
                        bootstrapReady = bootstrapReady,
                        bootstrapSecondsLeft = bootstrapSecondsLeft,
                        bootstrapExpired = bootstrapExpired,
                        onClearError = vm::clearAuthError,
                        onRegDoneDismiss = vm::dismissRegDone,
                        onSyncBootstrap = {
                            vm.reconcileLoginBootstrapSession(this@MainActivity)
                            vm.ensureBootstrapForAuthFlow(this@MainActivity)
                        },
                        onCloseApp = {
                            vm.shutdownBeforeExit(this@MainActivity)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                                finishAndRemoveTask()
                            } else {
                                finishAffinity()
                            }
                        },
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
                                VpnState.CONNECTED ->
                                    vm.disconnect(this@MainActivity)
                                VpnState.CONNECTING, VpnState.DISCONNECTING -> Unit
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
                        onDeleteDevice = { deviceId, onResult ->
                            vm.deleteDevice(deviceId) { ok, msg ->
                                if (ok && msg == "__logout__") {
                                    vm.logout(this@MainActivity)
                                    onResult(true, null)
                                } else {
                                    if (!ok && msg != null) vm.showError(msg)
                                    onResult(ok, msg)
                                }
                            }
                        },
                        onDevicesScreenActive = vm::setSessionsScreenActive,
                        onVpnProfilePolling = vm::setVpnProfilePolling,
                        updateInfo = updateInfo,
                        updateDownloading = updateDownloading,
                        updateProgress = updateProgress,
                        onUpdateClick = {
                            vm.downloadAndInstallUpdate(this@MainActivity) { intent ->
                                launchApkInstall(intent)
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
        handleNotificationOpenIntent(intent)
        handleTileConnectIntent(intent)
    }

    private fun handleNotificationOpenIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_OPEN_MAIN, false) != true) return
        intent.removeExtra(EXTRA_OPEN_MAIN)
        pendingNotificationOpen = true
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

    private fun launchApkInstall(intent: Intent) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O || packageManager.canRequestPackageInstalls()) {
            installUpdateLauncher.launch(intent)
            return
        }
        pendingInstallIntent = intent
        val settingsIntent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:$packageName"),
        )
        unknownSourcesLauncher.launch(settingsIntent)
    }

    override fun onResume() {
        super.onResume()
        isForeground = true
        SessionTrace.mark("MainActivity.onResume")
        val fromNotification = pendingNotificationOpen
        if (fromNotification) {
            pendingNotificationOpen = false
            window.decorView.post { vm.onReturnedToApp() }
        } else {
            vm.onAppResumed()
        }
        if (!fromNotification && ManlCaptchaWebViewManager.isCaptchaPending) {
            ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(this)
        }
    }

    override fun onPause() {
        isForeground = false
        SessionTrace.mark("MainActivity.onPause")
        super.onPause()
    }
}
