package com.silent.vpn

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.drawable.ColorDrawable
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.lifecycle.ViewModelProvider
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.components.LaunchSplash
import com.silent.vpn.util.DevicePlatform
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.delay

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    companion object {
        @Volatile
        var isForeground: Boolean = false

        const val EXTRA_OPEN_MAIN = "open_main"
        const val EXTRA_TILE_CONNECT = "tile_connect"
        private const val SPLASH_MIN_PHONE_MS = 900L
        private const val SPLASH_MIN_TV_MS = 500L

        @Volatile
        private var splashDoneThisProcess = false

        fun openIntent(context: Context): Intent =
            Intent(context, MainActivity::class.java).apply {
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
                putExtra(EXTRA_OPEN_MAIN, true)
            }

        fun tileConnectIntent(context: Context): Intent =
            openIntent(context).apply { putExtra(EXTRA_TILE_CONNECT, true) }
    }

    private var vm: MainViewModel? = null
    private var mainUiReady = false
    private var deviceIsTv = false

    private fun requireVm(): MainViewModel {
        vm?.let { return it }
        return ViewModelProvider(this)[MainViewModel::class.java].also {
            vm = it
            mainUiReady = true
        }
    }

    private var vpnPermissionGranted = mutableStateOf(false)
    private var pendingBootstrapAfterPermission = mutableStateOf(false)

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* optional */ }

    private val vpnPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            if (pendingBootstrapAfterPermission.value) {
                pendingBootstrapAfterPermission.value = false
                requireVm().ensureBootstrapForAuthFlow(this)
            } else {
                vpnPermissionGranted.value = true
            }
        } else {
            pendingBootstrapAfterPermission.value = false
        }
    }

    private var pendingNotificationOpen = false
    private var pendingInstallIntent: Intent? = null

    private fun applyLaunchWindowBackground() {
        val mode = runCatching {
            SilentPrefs.open(this)
                .getString(SilentRepository.PREF_APPEARANCE_MODE, null)
                ?.takeIf { it == "dark" || it == "light" }
        }.getOrNull()
        val bg = if (mode == "dark") 0xFF0B0F1A.toInt() else 0xFFFFFFFF.toInt()
        window.setBackgroundDrawable(ColorDrawable(bg))
    }

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
            requireVm().showError("Разрешите установку из неизвестных источников для завершения обновления")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        deviceIsTv = DevicePlatform.isTv(this)
        if (!deviceIsTv) {
            enableEdgeToEdge()
        }
        super.onCreate(savedInstanceState)
        applyLaunchWindowBackground()
        if (deviceIsTv) {
            WindowCompat.setDecorFitsSystemWindows(window, true)
        }

        pendingNotificationOpen = intent?.getBooleanExtra(EXTRA_OPEN_MAIN, false) == true
        if (pendingNotificationOpen) {
            intent?.removeExtra(EXTRA_OPEN_MAIN)
        }

        setContent {
            val skipSplash = splashDoneThisProcess || savedInstanceState != null
            var bootVm by remember {
                mutableStateOf<MainViewModel?>(if (skipSplash) requireVm() else null)
            }
            LaunchedEffect(Unit) {
                if (bootVm != null) return@LaunchedEffect
                val minMs = if (deviceIsTv) SPLASH_MIN_TV_MS else SPLASH_MIN_PHONE_MS
                val start = System.currentTimeMillis()
                val model = requireVm()
                val remain = minMs - (System.currentTimeMillis() - start)
                if (remain > 0) delay(remain)
                splashDoneThisProcess = true
                bootVm = model
            }
            if (bootVm == null) {
                LaunchSplash()
            } else {
                MainActivityRoot(
                    activity = this,
                    vm = bootVm!!,
                    isTv = deviceIsTv,
                    vpnPermissionGranted = vpnPermissionGranted,
                    pendingBootstrapAfterPermission = pendingBootstrapAfterPermission,
                    onLaunchVpnPermission = { vpnPermissionLauncher.launch(it) },
                    onLaunchApkInstall = ::launchApkInstall,
                    initialIntent = intent,
                )
            }
        }

        window.decorView.post {
            SessionTrace.mark("MainActivity.onCreate", BuildConfig.VERSION_NAME)
            DebugLog.i(
                "App",
                "Silent VPN ${android.os.Build.MODEL} API ${android.os.Build.VERSION.SDK_INT} TV=$deviceIsTv ABI=${DevicePlatform.primaryAbi()}",
            )
            if (!deviceIsTv && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED
                ) {
                    notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                }
            }
            if (deviceIsTv) {
                window.decorView.requestFocus()
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleNotificationOpenIntent(intent)
        handleTileConnectIntent(intent)
        handleReferralDeepLink(intent)
        handlePaymentDeepLink(intent)
    }

    fun handleReferralDeepLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "silentvpn" || data.host != "ref") return
        val code = data.getQueryParameter("code")?.trim().orEmpty()
        if (code.isBlank()) return
        intent.data = null
        vm?.applyReferralDeepLink(code)
    }

    fun handlePaymentDeepLink(intent: Intent?) {
        val data = intent?.data ?: return
        if (data.scheme != "silentvpn" || data.host != "payment") return
        intent.data = null
        vm?.onPaymentReturnedFromBrowser()
    }

    private fun handleNotificationOpenIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_OPEN_MAIN, false) != true) return
        intent.removeExtra(EXTRA_OPEN_MAIN)
        pendingNotificationOpen = true
    }

    fun handleTileConnectIntent(intent: Intent?) {
        if (intent?.getBooleanExtra(EXTRA_TILE_CONNECT, false) != true) return
        intent.removeExtra(EXTRA_TILE_CONNECT)
        if (SilentVpnService.isRunning) return
        val model = vm ?: return
        if (!model.repository.isLoggedIn()) return
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
        if (!mainUiReady) return
        val model = vm ?: return
        val fromNotification = pendingNotificationOpen
        if (fromNotification) {
            pendingNotificationOpen = false
            window.decorView.post { model.onReturnedToApp() }
        } else {
            model.onAppResumed()
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
