package com.silent.vpn

import android.content.Intent
import android.net.Uri
import android.net.VpnService
import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import com.silent.vpn.ui.screens.LoginScreen
import com.silent.vpn.ui.screens.MainScreen
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.ui.theme.AppearanceMode
import com.silent.vpn.ui.theme.DarkSystemBarStrip
import com.silent.vpn.ui.theme.SilentTheme
import com.silent.vpn.util.LocalIsTv
import com.silent.vpn.vpn.WdttTunnelManager
import kotlinx.coroutines.delay

/** Основной UI — монтируется только после splash, чтобы не блокировать первый кадр ViewModel-ом. */
@Composable
fun MainActivityRoot(
    activity: MainActivity,
    vm: MainViewModel,
    isTv: Boolean,
    vpnPermissionGranted: MutableState<Boolean>,
    pendingBootstrapAfterPermission: MutableState<Boolean>,
    onLaunchVpnPermission: (Intent) -> Unit,
    onLaunchApkInstall: (Intent) -> Unit,
    initialIntent: Intent?,
) {
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
    val pendingReferralCode by vm.pendingReferralCode.collectAsState()
    val paymentState by vm.paymentState.collectAsState()
    val openSubscriptionMenu by vm.openSubscriptionMenu.collectAsState()

    LaunchedEffect(Unit) {
        activity.handleTileConnectIntent(initialIntent)
        activity.handleReferralDeepLink(initialIntent)
        activity.handlePaymentDeepLink(initialIntent)
    }

    LaunchedEffect(vpnPermissionGranted.value) {
        if (vpnPermissionGranted.value) {
            vpnPermissionGranted.value = false
            vm.connect(activity)
        }
    }

    LaunchedEffect(screen) {
        if (screen != AppScreen.LOGIN) return@LaunchedEffect
        if (isTv) delay(150)
        vm.reconcileLoginBootstrapSession(activity)
        val prep = VpnService.prepare(activity)
        if (prep != null) {
            pendingBootstrapAfterPermission.value = true
            WdttTunnelManager.traceApp("vpn_permission", "запрос разрешения VPN у системы")
            onLaunchVpnPermission(prep)
        } else {
            WdttTunnelManager.traceApp("vpn_permission", "разрешение VPN уже есть")
            vm.ensureBootstrapForAuthFlow(activity)
        }
    }

    CompositionLocalProvider(LocalIsTv provides isTv) {
        var appearanceDark by remember { mutableStateOf(vm.repository.getAppearanceMode() == "dark") }
        val appearanceMode = if (appearanceDark) AppearanceMode.DARK else AppearanceMode.LIGHT
        SilentTheme(themeData = theme, darkTheme = appearanceDark) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(
                        if (appearanceDark) DarkSystemBarStrip
                        else MaterialTheme.colorScheme.background,
                    ),
            ) {
                when (screen) {
                    AppScreen.LOGIN -> LoginScreen(
                        theme = theme,
                        initialEmail = vm.lastEmail,
                        initialPassword = vm.lastPassword,
                        initialRememberMe = vm.rememberMe,
                        initialReferralOrPromo = pendingReferralCode,
                        forgotSent = forgotSent,
                        onLogin = { email, password, remember ->
                            vm.login(email, password, remember, activity)
                        },
                        onRegister = { email, password, remember, referral ->
                            vm.register(email, password, remember, referral)
                        },
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
                            vm.reconcileLoginBootstrapSession(activity)
                            vm.ensureBootstrapForAuthFlow(activity)
                        },
                        onCloseApp = {
                            vm.shutdownBeforeExit(activity)
                            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                                activity.finishAndRemoveTask()
                            } else {
                                activity.finishAffinity()
                            }
                        },
                        appearanceMode = appearanceMode,
                        onToggleAppearance = {
                            val next = vm.repository.toggleAppearanceMode()
                            appearanceDark = next == "dark"
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
                                    val prep = VpnService.prepare(activity)
                                    if (prep != null) onLaunchVpnPermission(prep)
                                    else vm.connect(activity)
                                }
                                VpnState.CONNECTED -> vm.disconnect(activity)
                                VpnState.CONNECTING, VpnState.DISCONNECTING -> Unit
                            }
                        },
                        onLogout = { vm.logout(activity) },
                        onClearVpnError = vm::clearVpnError,
                        onCheckPromo = vm::checkPromo,
                        onLoadReferral = vm::loadReferral,
                        onInitPayment = vm::initPayment,
                        paymentState = paymentState,
                        openSubscriptionMenu = openSubscriptionMenu,
                        onSubscriptionMenuOpened = vm::consumeOpenSubscriptionMenu,
                        onStartPaymentPoll = vm::startPaymentPoll,
                        onResetPaymentState = vm::resetPaymentState,
                        onOpenUrl = { url ->
                            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                        },
                        onShowError = vm::showError,
                        onRenameDevice = vm::renameDevice,
                        onDeleteDevice = { deviceId, onResult ->
                            vm.deleteDevice(deviceId) { ok, msg ->
                                if (ok && msg == "__logout__") {
                                    vm.logout(activity)
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
                            vm.downloadAndInstallUpdate(activity, onLaunchApkInstall)
                        },
                        onUpdatePolling = vm::setUpdatePolling,
                        appearanceMode = appearanceMode,
                        onToggleAppearance = {
                            val next = vm.repository.toggleAppearanceMode()
                            appearanceDark = next == "dark"
                        },
                        onEnsureOlcrtcApi = { providers ->
                            vm.cancelPendingOlcrtcConnectForApply()
                            vm.ensureOlcrtcConfigApi(activity, *providers)
                        },
                    )
                }
            }
        }
    }
}
