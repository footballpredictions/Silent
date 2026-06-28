package com.silent.vpn

import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.silent.vpn.auth.CredentialHelper
import com.silent.vpn.data.BootstrapConfigRequest
import com.silent.vpn.data.BootstrapVpnConfig
import com.silent.vpn.data.ConnectRequest
import com.silent.vpn.data.DeviceRegisterRequest
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.ForgotPasswordRequest
import com.silent.vpn.data.ConfigSyncCoordinator
import com.silent.vpn.data.HashItemDto
import com.silent.vpn.data.LoginDeviceInfo
import com.silent.vpn.data.LoginRequest
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.activeServerHashes
import com.silent.vpn.data.toHashItems
import com.silent.vpn.data.PromoCheckRequest
import com.silent.vpn.data.RegisterRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.data.VpnHashesResponse
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.service.VpnBackendSync
import com.silent.vpn.service.VpnServiceTracker
import com.silent.vpn.service.VpnConnectHelper
import com.silent.vpn.service.VpnSessionState
import com.silent.vpn.service.VpnTileConnect
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.vk.HashParser
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.HashFailureReporter
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.update.AppUpdateManager
import com.silent.vpn.data.UpdateCheckResponse
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Dispatchers
import java.util.concurrent.ConcurrentLinkedQueue
import kotlinx.coroutines.delay
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import javax.inject.Inject
import retrofit2.Response

private const val BOOTSTRAP_SESSION_MS = 2 * 60 * 1000L
private const val EPHEMERAL_TUNNEL_WAIT_ITER = 120
private const val BOOTSTRAP_EXPIRED_MSG =
    "Время временного интернета истекло (2 мин). Закройте приложение и запустите снова."
/** Пока открыт экран «Устройства/Сессии» и VPN ВЫКЛЮЧЕН — обновляем список по public API. */
private const val SESSIONS_POLL_MS = 10 * 1000L

enum class AppScreen { LOGIN, MAIN }

@HiltViewModel
class MainViewModel @Inject constructor(
    private val repo: SilentRepository,
    @ApplicationContext private val appContext: Context,
) : ViewModel() {

    private val _screen = MutableStateFlow(if (repo.isLoggedIn()) AppScreen.MAIN else AppScreen.LOGIN)
    val screen: StateFlow<AppScreen> = _screen

    private val _profile = MutableStateFlow<UserProfile?>(null)
    val profile: StateFlow<UserProfile?> = _profile

    private val _vpnState = MutableStateFlow(VpnState.DISCONNECTED)
    val vpnState: StateFlow<VpnState> = _vpnState

    private val _theme = MutableStateFlow<ThemeData?>(null)
    val theme: StateFlow<ThemeData?> = _theme

    private val _authLoading = MutableStateFlow(false)
    val authLoading: StateFlow<Boolean> = _authLoading

    private val _authError = MutableStateFlow<String?>(null)
    val authError: StateFlow<String?> = _authError

    private val _vpnError = MutableStateFlow<String?>(null)
    val vpnError: StateFlow<String?> = _vpnError

    private val _accountRefreshing = MutableStateFlow(false)
    val accountRefreshing: StateFlow<Boolean> = _accountRefreshing

    private val _regDone = MutableStateFlow(false)
    val regDone: StateFlow<Boolean> = _regDone

    private val _regEmail = MutableStateFlow("")
    val regEmail: StateFlow<String> = _regEmail

    private val _bootstrapHash = MutableStateFlow(repo.getBootstrapHash())
    val bootstrapHash: StateFlow<String?> = _bootstrapHash

    private val _hashReady = MutableStateFlow(isHashReady())
    val hashReady: StateFlow<Boolean> = _hashReady

    private val _statusMsg = MutableStateFlow("")
    val statusMsg: StateFlow<String> = _statusMsg

    private val _bootstrapConnecting = MutableStateFlow(false)
    val bootstrapConnecting: StateFlow<Boolean> = _bootstrapConnecting

    /** Секунд до конца bootstrap-сессии (2 мин); null — таймер не идёт. */
    private val _bootstrapSecondsLeft = MutableStateFlow<Int?>(null)
    val bootstrapSecondsLeft: StateFlow<Int?> = _bootstrapSecondsLeft

    /** Bootstrap-сессия истекла — блокируем повторный VPN и показываем экран закрытия. */
    private val _bootstrapExpired = MutableStateFlow(false)
    val bootstrapExpired: StateFlow<Boolean> = _bootstrapExpired

    /** VPN для входа/регистрации/сброса пароля готов (сервис + туннель), единый источник для UI. */
    private val _bootstrapReady = MutableStateFlow(false)
    val bootstrapReady: StateFlow<Boolean> = _bootstrapReady

    private val _sessionDeviceId = MutableStateFlow(repo.getSessionDeviceId())
    val sessionDeviceId: StateFlow<String?> = _sessionDeviceId

    private var bootstrapVpnMode = false
    private var bootstrapConnectingInternal = false
    private var bootstrapTimeoutJob: Job? = null
    private var bootstrapContext: Context? = null
    /** Дедлайн 2 мин — один на сессию, не сбрасывается при переходе шаг 2 → шаг 1. */
    private var bootstrapDeadlineMs = 0L
    private var silentBootstrapSync = false
    private var profilePollJob: Job? = null
    @Volatile private var sessionsFetchInFlight = false
    private var updateApiBaseUrl: String? = null
    /** One-shot: пользователь уже нажал CONNECT, ждём обновление подписки и повторяем автоматически. */
    private var pendingConnectAfterSubscriptionRefresh = false
    /** Должен быть объявлен до init — tunnelReady.collect может сработать в конструкторе. */
    private val pendingHashFailures = ConcurrentLinkedQueue<Triple<String, String, String>>()
    private var hashFailureFlushJob: Job? = null

    private val configSyncListener = object : ConfigSyncCoordinator.Listener {
        override fun onTheme(theme: ThemeData) {
            _theme.value = theme
        }

        override fun onProfile(profile: UserProfile) {
            applyServerProfile(profile)
        }

        override fun onHashesUpdated(items: List<HashItemDto>, applyToTunnel: Boolean) {
            clearBootstrapIfServerHashesReady(items)
            refreshHashState()
            if (applyToTunnel) {
                val serverHashes = items.activeServerHashes().map { it.hash }
                if (serverHashes.isNotEmpty()) {
                    val applied = WdttTunnelManager.applyUpdatedVkHashes(appContext, serverHashes)
                    DebugLog.i("MainViewModel", "config sync hash apply tunnel=$applied")
                }
            }
        }

        override fun isPollAllowed(): Boolean =
            repo.isLoggedIn() &&
                !bootstrapVpnMode &&
                _screen.value == AppScreen.MAIN &&
                repo.allowsBackgroundConfigSync()

        override fun onWifiSyncTickStart() {
            flushPendingHashFailures()
        }

        override fun vpnState(): VpnState = _vpnState.value
    }

    private fun startConfigSync() {
        ConfigSyncCoordinator.start(viewModelScope, repo, appContext, configSyncListener)
    }

    private fun stopConfigSync() {
        ConfigSyncCoordinator.stop()
    }

    private suspend fun seedConfigSyncRevision() {
        runCatching {
            repo.fetchSyncState().getOrNull()?.let { state ->
                // revision хешей — только после успешной загрузки (pull/tick), иначе sync «залипает»
                repo.saveSyncThemeRev(state.theme)
                repo.saveSyncProfileRev(state.profile)
            }
        }
    }

    private val _updateInfo = MutableStateFlow<UpdateCheckResponse?>(null)
    val updateInfo: StateFlow<UpdateCheckResponse?> = _updateInfo

    private val _updateProgress = MutableStateFlow(0)
    val updateProgress: StateFlow<Int> = _updateProgress

    private val _updateDownloading = MutableStateFlow(false)
    val updateDownloading: StateFlow<Boolean> = _updateDownloading

    private val _forgotSent = MutableStateFlow(false)
    val forgotSent: StateFlow<Boolean> = _forgotSent

    val lastEmail: String get() = repo.getLastEmail().orEmpty()
    val lastPassword: String get() = repo.getRememberedPassword().orEmpty()
    val rememberMe: Boolean get() = repo.getRememberMe()
    val repository: SilentRepository get() = repo

    private fun isHashReady(): Boolean = !repo.getBootstrapHash().isNullOrBlank()

    private fun refreshHashState() {
        _bootstrapHash.value = repo.getBootstrapHash()
        _hashReady.value = isHashReady()
    }

    /** После login bootstrap VPN отключается; legacy prefs очищаем. */
    private fun clearBootstrapHashAfterLogin() {
        if (!repo.isLoggedIn()) return
        repo.clearBootstrapHash()
        refreshHashState()
        DebugLog.i("MainViewModel", "bootstrap session cleared after login")
    }

    private fun clearBootstrapIfServerHashesReady(items: List<HashItemDto>) {
        if (items.activeServerHashes().isEmpty()) return
        clearBootstrapHashAfterLogin()
    }

    init {
        HashFailureReporter.install { hash, errorType, message ->
            if (!repo.isLoggedIn() || bootstrapVpnMode) return@install
            if (repo.isOnMobileData() && !repo.allowsBackgroundConfigSync()) {
                pendingHashFailures.add(Triple(hash, errorType, message))
                DebugLog.i("MainViewModel", "hash failure queued (mobile, no VPN): ${hash.take(8)}…")
                return@install
            }
            if (WdttTunnelManager.isWorkerRampUpActive() ||
                !VpnSessionState.tunnelDataSyncCompleted ||
                (_vpnState.value == VpnState.CONNECTING && !WdttTunnelManager.tunnelReady.value)
            ) {
                pendingHashFailures.add(Triple(hash, errorType, message))
                DebugLog.i("MainViewModel", "hash failure queued (connect sync): ${hash.take(8)}…")
                return@install
            }
            viewModelScope.launch {
                repo.reportHashFailure(hash, errorType, message)
                    .onFailure { e -> DebugLog.w("MainViewModel", "hash failure report: ${e.message}") }
            }
        }
        if (repo.isLoggedIn()) {
            if (!repo.hasSessionFingerprint()) {
                runCatching { repo.startNewSession() }
                    .onFailure { e ->
                        DebugLog.w("MainViewModel", "restore session fingerprint failed: ${e.message}")
                        repo.clearTokens()
                        _screen.value = AppScreen.LOGIN
                    }
            } else {
                _screen.value = AppScreen.MAIN
                restoreCachedProfileToUi()
                restoreCachedThemeToUi()
                syncVpnStateFromSystem()
                viewModelScope.launch {
                    runCatching { refreshSession() }
                        .onFailure { e ->
                            DebugLog.w("MainViewModel", "refreshSession: ${e.message}")
                        }
                }
                repo.mergeSavedHashesIntoCachedConfig()
                startConfigSync()
            }
        } else {
            loadTheme()
            if (SilentVpnService.isRunning && isHashReady()) {
                reconcileLoginBootstrapSession(appContext)
            }
        }
        com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener = configSyncListener
        com.silent.vpn.sync.VpnDataSyncBridge.onCycleCompleted = { checkForAppUpdate() }
        checkForAppUpdate()
        viewModelScope.launch {
            WdttTunnelManager.lastError.collect { err ->
                if (!err.isNullOrBlank() &&
                    (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.CONNECTED)
                ) {
                    DebugLog.e("MainViewModel", "WDTT error: $err")
                    _vpnError.value = err
                    if (bootstrapVpnMode) {
                        _vpnState.value = VpnState.DISCONNECTED
                        bootstrapVpnMode = false
                        cancelBootstrapSessionTimeout()
                        bootstrapContext?.let { stopVpnLocally(it) }
                        _statusMsg.value = err
                    }
                }
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.tunnelReady.collect { ready ->
                if (ready) {
                    if (_vpnState.value == VpnState.DISCONNECTING) return@collect
                    DebugLog.i("MainViewModel", "tunnel ready")
                    if (bootstrapVpnMode && WdttTunnelManager.isBootstrapMode()) {
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady()
                        val ctx = bootstrapContext
                        if (ctx != null) {
                            startBootstrapSessionTimeout(
                                ctx,
                                forceNewDeadline = bootstrapDeadlineMs <= System.currentTimeMillis(),
                            )
                        }
                    } else if (silentBootstrapSync) {
                        // Ephemeral API sync — runEphemeralApiBootstrap polls tunnelReady itself.
                    } else if (SilentVpnService.isRunning) {
                        if (!repo.isLoggedIn() && _screen.value == AppScreen.LOGIN) {
                            bootstrapVpnMode = true
                            bootstrapContext = bootstrapContext ?: appContext
                            startBootstrapSessionTimeout(
                                appContext,
                                forceNewDeadline = bootstrapDeadlineMs <= System.currentTimeMillis(),
                            )
                        }
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady()
                        updateBootstrapReadyFlag()
                    }
                } else if (
                    _vpnState.value == VpnState.CONNECTED &&
                    !WdttTunnelManager.running.value &&
                    WdttTunnelManager.activeWorkers.value < 1
                ) {
                    _vpnState.value = VpnState.DISCONNECTED
                    backendSyncCompleted = false
                    repo.clearTunnelApiBase()
                    markLocalDeviceOffline()
                }
            }
        }
    }

    private suspend fun refreshSession() {
        loadTheme()
        restoreCachedProfileToUi()
        repo.mergeSavedHashesIntoCachedConfig()
        if (SilentVpnService.isRunning && VpnSessionState.isActive()) {
            if (_profile.value == null) {
                fetchProfileNow(force = true)
            }
            ensureVpnConfigRestored(appContext)
            return
        }
        fetchProfileNow(force = _profile.value == null)
        if (!SilentVpnService.isRunning) {
            syncServerHashes(preferPublicOnly = true)
        }
        ensureVpnConfigRestored(appContext)
    }

    /**
     * После OTA кеш WG мог быть сброшен — восстанавливаем через bootstrap по сохранённому хешу,
     * чтобы connect работал на мобильном интернете без Wi‑Fi.
     */
    private suspend fun ensureVpnConfigRestored(context: Context): Boolean {
        val cached = loadCachedVpnConfig()
        if (cached != null && isConfigConnectable(cached)) {
            repo.mergeSavedHashesIntoCachedConfig()
            return true
        }
        if (!repo.isLoggedIn() || !repo.hasMainVpnServerHashes()) return false
        if (silentBootstrapSync || bootstrapVpnMode) return false
        if (SilentVpnService.isRunning || WdttTunnelManager.running.value) return false

        val bootHash = repo.mainVpnServerHashes().firstOrNull() ?: return false
        val fp = runCatching { repo.getDeviceFingerprint() }.getOrNull() ?: return false

        silentBootstrapSync = true
        val prevBootstrap = bootstrapVpnMode
        try {
            var config = runCatching {
                val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(bootHash, "android", fp))
                if (res.isSuccessful) bootstrapLaunchConfig(res.body()!!) else null
            }.getOrNull()
            if (config == null || config.vk_hashes.isEmpty()) {
                config = bootstrapLaunchConfig(BootstrapVpnConfig.build(bootHash, fp))
            }
            if (config.vk_hashes.isEmpty()) return false
            DebugLog.i("MainViewModel", "restore VPN config via saved hash bootstrap")
            bootstrapVpnMode = true
            launchVpnService(context.applicationContext, config, forceBootstrap = true)
            repeat(75) {
                delay(200)
                if (WdttTunnelManager.tunnelReady.value) {
                    withBootstrapBackendApi { applyRefreshVpnConfigDirect(fp) }
                    val restored = loadCachedVpnConfig()
                    return restored != null && isConfigConnectable(restored)
                }
            }
            return false
        } catch (e: Exception) {
            DebugLog.w("MainViewModel", "ensureVpnConfigRestored: ${e.message}")
            return false
        } finally {
            stopVpnLocally(context.applicationContext)
            repo.clearTunnelApiBase()
            bootstrapVpnMode = prevBootstrap
            silentBootstrapSync = false
        }
    }

    /** Профиль и хеши через bootstrap-туннель до отключения временного VPN. */
    private suspend fun syncLoginDataViaBootstrapTunnel(registerIfNeeded: Boolean = true): Boolean {
        if (!WdttTunnelManager.tunnelReady.value) return false
        val tunnel = WdttTunnelManager.tunnelApiBase()
        repo.useApiBase(tunnel)
        runCatching {
            val fp = repo.getDeviceFingerprint()
            var cfg = runCatching {
                val res = repo.getApi().getConfig(fp)
                if (res.isSuccessful) res.body() else null
            }.getOrNull()
            if (cfg == null && registerIfNeeded) {
                val reg = repo.getApi().registerDevice(
                    DeviceRegisterRequest(repo.getDeviceDisplayName(), "android", fp, null, repo.getBootstrapHash()),
                )
                if (reg.isSuccessful) cfg = reg.body()
            }
            if (cfg != null) {
                repo.saveSessionDeviceId(cfg.device_id)
                _sessionDeviceId.value = cfg.device_id
                repo.cacheVpnConfig(Gson().toJson(cfg))
                DebugLog.i("MainViewModel", "login cache device=${cfg.device_id.take(8)} hashes=${cfg.vk_hashes.size}")
            }
        }.onFailure { e ->
            DebugLog.w("MainViewModel", "login config sync: ${e.message}")
        }
        val items = runCatching {
            repo.fetchAndSaveHashItemsViaTunnel().getOrDefault(emptyList())
        }.getOrElse {
            DebugLog.w("MainViewModel", "login hash sync: ${it.message}")
            repo.getSavedHashItems()
        }
        clearBootstrapIfServerHashesReady(items)
        repo.mergeSavedHashesIntoCachedConfig()
        clearBootstrapHashAfterLogin()
        // ВАЖНО: тянем профиль напрямую по tunnel-base, пока активен API-overlay.
        // fetchProfileNow() здесь нельзя — он сразу выходит при isApiOverlayActive()==true,
        // поэтому профиль не грузился, и пользователь видел «Включите главный тумблер».
        return tryFetchProfileOnBase(tunnel) || _profile.value != null
    }

    /** Главный экран только после входа; bootstrap/pre-login остаётся на LOGIN. */
    private fun isMainVpnSessionForUi(): Boolean =
        repo.isLoggedIn() && !bootstrapVpnMode && !WdttTunnelManager.isBootstrapMode()

    private fun restoreVpnUiAfterForeground() {
        if (_vpnState.value != VpnState.CONNECTED) {
            _vpnState.value = VpnState.CONNECTED
        }
        restoreCachedProfileToUi()
        restoreCachedThemeToUi()
    }

    fun onReturnedToApp() {
        if (!repo.isLoggedIn()) {
            reconcileLoginBootstrapSession(appContext)
        }
        if (SilentVpnService.isRunning && VpnSessionState.isActive()) {
            if (isMainVpnSessionForUi()) {
                _screen.value = AppScreen.MAIN
                restoreVpnUiAfterForeground()
            } else {
                _screen.value = AppScreen.LOGIN
                restoreVpnUiAfterForeground()
            }
            return
        }
        syncSessionOnResume()
    }

    fun onAppResumed() {
        if (!repo.isLoggedIn()) {
            reconcileLoginBootstrapSession(appContext)
        } else if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            restartBootstrapTimerIfNeeded()
        }
        if (SilentVpnService.isRunning && VpnSessionState.isActive()) {
            if (isMainVpnSessionForUi()) {
                if (_screen.value != AppScreen.MAIN) _screen.value = AppScreen.MAIN
                restoreVpnUiAfterForeground()
            } else {
                _screen.value = AppScreen.LOGIN
                restoreVpnUiAfterForeground()
            }
            return
        }
        syncSessionOnResume()
    }

    private fun restoreCachedProfileToUi() {
        repo.getCachedProfile()?.let { cached ->
            if (_profile.value == null) _profile.value = cached
        }
    }

    private fun restoreCachedThemeToUi(refreshFromSync: Boolean = false) {
        repo.getCachedTheme()?.let { cached ->
            if (refreshFromSync || _theme.value == null) _theme.value = cached
        }
    }

    private fun syncVpnStateFromSystem() {
        SessionTrace.enter("MainViewModel.syncVpnStateFromSystem")
        VpnServiceTracker.reconcileStaleSession(appContext)
        when {
            VpnSessionState.isActive() -> {
                _vpnState.value = VpnState.CONNECTED
                restoreCachedProfileToUi()
                restoreCachedThemeToUi()
                if (!isMainVpnSessionForUi()) {
                    _screen.value = AppScreen.LOGIN
                }
            }
            SilentVpnService.isRunning -> {
                _vpnState.value = VpnState.CONNECTED
                if (isMainVpnSessionForUi()) {
                    SessionTrace.mark("MainViewModel.syncVpnStateFromSystem", "CONNECTED attach")
                    attachExistingSession()
                } else {
                    SessionTrace.mark("MainViewModel.syncVpnStateFromSystem", "bootstrap attach")
                    _screen.value = AppScreen.LOGIN
                    reconcileLoginBootstrapSession(appContext)
                }
            }
            else -> {
                _vpnState.value = VpnState.DISCONNECTED
                SessionTrace.mark("MainViewModel.syncVpnStateFromSystem", "DISCONNECTED")
            }
        }
        SessionTrace.exit("MainViewModel.syncVpnStateFromSystem")
    }

    /** Подключиться к уже работающему туннелю (плитка QS / resume). */
    private fun attachExistingSession() {
        if (_vpnState.value == VpnState.DISCONNECTING) return
        onVpnTunnelReady(initialConnect = false)
        restoreCachedProfileToUi()
    }

    private fun syncSessionOnResume() {
        SessionTrace.enter("MainViewModel.syncSessionOnResume")
        if (!repo.isLoggedIn()) {
            reconcileLoginBootstrapSession(appContext)
            SessionTrace.exit("MainViewModel.syncSessionOnResume", "not logged in")
            return
        }
        _screen.value = AppScreen.MAIN
        _authLoading.value = false
        restoreCachedProfileToUi()
        syncVpnStateFromSystem()
        resumeProfileJob?.cancel()
        resumeProfileJob = viewModelScope.launch {
            if (_profile.value == null && repo.isLoggedIn() && !VpnSessionState.isBusy()) {
                runCatching {
                    if (bootstrapVpnMode && SilentVpnService.isRunning) {
                        withBootstrapBackendApi { fetchProfileNow(force = true) }
                        if (_profile.value != null) {
                            disconnectBootstrapVpn(appContext)
                        }
                    } else {
                        fetchProfileNow(force = true)
                    }
                }.onFailure { e ->
                    DebugLog.w("MainViewModel", "resume profile fetch: ${e.message}")
                }
            }
            restoreCachedProfileToUi()
            if (SilentVpnService.isRunning && VpnSessionState.isActive()) {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _vpnState.value = VpnState.CONNECTED
                }
                // Без overlay-обновления при resume — данные из кеша; свежие приходят при connect.
            }
        }
        SessionTrace.exit("MainViewModel.syncSessionOnResume", "vpn=${_vpnState.value}")
    }

    /**
     * Краткий bootstrap-туннель для API на LTE (белые списки): профиль, хеши, WG-config.
     * Только по действию пользователя или перед connect; не фоновый poll.
     */
    private suspend fun runEphemeralApiBootstrap(
        context: Context,
        force: Boolean = false,
        apiBlock: (suspend () -> Boolean)? = null,
    ): Boolean {
        if (!repo.isLoggedIn() || !isHashReady()) return false
        if (silentBootstrapSync || bootstrapVpnMode) return false
        if (repo.isMainVpnTunnelUp()) return false
        if (!repo.mayRunEphemeralSync(force)) {
            DebugLog.i("MainViewModel", "ephemeral sync throttled")
            return false
        }
        if (!repo.isOnMobileData() && repo.isPublicBackendReachable(forceProbe = true)) {
            return false
        }

        val boot = HashParser.extract(repo.getBootstrapHash().orEmpty()) ?: return false
        val fp = runCatching { repo.getDeviceFingerprint() }.getOrNull() ?: return false

        silentBootstrapSync = true
        try {
            repo.clearTunnelApiBase()
            var config = runCatching {
                val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(boot, "android", fp))
                if (res.isSuccessful) bootstrapLaunchConfig(res.body()!!) else null
            }.getOrNull()
            if (config == null || config.vk_hashes.isEmpty()) {
                config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))
            }
            if (config.vk_hashes.isEmpty()) return false

            DebugLog.i("MainViewModel", "ephemeral API bootstrap start")
            launchVpnService(context.applicationContext, config, forceBootstrap = true)
            var apiOk = false
            var attempt = 0
            while (attempt < EPHEMERAL_TUNNEL_WAIT_ITER && !apiOk) {
                delay(250)
                if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.isBootstrapMode()) {
                    attempt++
                    continue
                }
                if (WdttTunnelManager.activeWorkers.value < 1 && attempt < 24) {
                    attempt++
                    continue
                }
                // Bootstrap-VPN включает app в туннель (APP_EXCLUDED=false) — без этого HTTP к 10.66.66.1 не идёт.
                if (WdttTunnelManager.isBootstrapMode() && SilentRepository.APP_EXCLUDED_FROM_VPN && attempt < 32) {
                    attempt++
                    continue
                }
                if (attempt == 0 || attempt == 8 || attempt == 16) delay(800)
                val ok = runCatching {
                    withEphemeralBackendApi {
                        if (apiBlock != null) {
                            apiBlock()
                        } else {
                            ephemeralAccountSync(fp)
                        }
                    }
                }.getOrElse { e ->
                    DebugLog.w("MainViewModel", "ephemeral API attempt failed: ${e.message}")
                    false
                }
                if (ok) {
                    apiOk = true
                    repo.markEphemeralSyncUsed()
                    DebugLog.i("MainViewModel", "ephemeral API bootstrap OK (attempt ${attempt + 1})")
                }
                attempt++
            }
            if (!apiOk) {
                DebugLog.w("MainViewModel", "ephemeral API bootstrap: profile/API not fetched")
            }
            return apiOk
        } catch (e: Exception) {
            DebugLog.w("MainViewModel", "ephemeral API bootstrap: ${e.message}")
            return false
        } finally {
            stopVpnLocally(context.applicationContext)
            repo.clearTunnelApiBase()
            silentBootstrapSync = false
            withContext(Dispatchers.IO) {
                VpnConnectHelper.ensureCleanSlate(context.applicationContext)
            }
        }
    }

    /** Профиль/подписка через уже поднятый ephemeral tunnel (без повторного routing). */
    private suspend fun ephemeralAccountSync(fp: String): Boolean {
        val tunnel = WdttTunnelManager.tunnelApiBase()
        if (!tryFetchProfileOnBase(tunnel)) {
            DebugLog.w(
                "MainViewModel",
                "ephemeral profile fetch failed via $tunnel excluded=${SilentRepository.APP_EXCLUDED_FROM_VPN}",
            )
            return false
        }
        runCatching { syncServerHashes() }
        runCatching { applyRefreshVpnConfigDirect(fp) }
        return true
    }

    /** API через ephemeral/bootstrap tunnel — тот же канал, что login/register на LTE. */
    private suspend fun <T> withEphemeralBackendApi(block: suspend () -> T): T {
        awaitTunnelApiReady()
        if (!WdttTunnelManager.isBootstrapMode() || !WdttTunnelManager.tunnelReady.value) {
            error("ephemeral tunnel not ready")
        }
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) {
            repo.ensureBootstrapTunnelApi()
            return block()
        }
        return WdttTunnelManager.withApiOverlay {
            repo.useApiBase(WdttTunnelManager.tunnelApiBase())
            repo.invalidateApiClient()
            block()
        }
    }

    private suspend fun tryTunnelAccountRefresh(): Boolean {
        if (!repo.isMainVpnTunnelUp()) return false
        return runCatching {
            repo.withUserBackendApi {
                val profileOk = fetchProfileNow(force = true)
                if (profileOk) syncServerHashes()
                profileOk
            }
        }.getOrDefault(false)
    }

    private suspend fun tryPublicAccountRefresh(): Boolean {
        if (repo.isOnMobileData()) return false
        repo.clearTunnelApiBase()
        return runCatching {
            repo.withBackendApi { fetchProfileNow(force = true) }
        }.getOrDefault(false).also { ok ->
            if (ok) syncServerHashes()
        }
    }

    /** Обновить профиль/подписку/хеши: tunnel (VPN ON) → Wi‑Fi public → ephemeral bootstrap (LTE). */
    fun refreshAccountData(force: Boolean = true, onResult: ((Boolean, String?) -> Unit)? = null) {
        viewModelScope.launch {
            if (_accountRefreshing.value) return@launch
            _accountRefreshing.value = true
            try {
                val subBefore = _profile.value?.subscription?.is_active
                var ok = tryTunnelAccountRefresh()
                if (!ok) ok = tryPublicAccountRefresh()
                if (!ok) ok = runEphemeralApiBootstrap(appContext, force = force)
                val subAfter = _profile.value?.subscription?.is_active
                val msg = when {
                    ok -> {
                        when {
                            subAfter == true ->
                                "Данные обновлены · подписка активна"
                            subAfter == false ->
                                "Данные обновлены · подписка не активна"
                            else -> "Данные обновлены"
                        }
                    }
                    repo.isMainVpnTunnelUp() ->
                        "Не удалось обновить через VPN-туннель. Подождите несколько секунд и повторите."
                    !force && !repo.mayRunEphemeralSync(force = true) -> {
                        val sec = repo.ephemeralSyncCooldownSec()
                        if (sec != null) "Подождите $sec сек. перед повтором." else null
                    }
                    else ->
                        "Не удалось получить профиль с сервера. Дождитесь подключения служебного туннеля и повторите."
                }
                if (ok && subBefore == subAfter && subBefore != null) {
                    DebugLog.i("MainViewModel", "refreshAccountData: subscription unchanged (active=$subAfter)")
                }
                onResult?.invoke(ok, msg)
            } finally {
                _accountRefreshing.value = false
            }
        }
    }

    private data class ConnectFetchResult(
        val vpnConfig: VpnConfig?,
        val apiError: String?,
        val accessDenied: Boolean,
    )

    private suspend fun fetchVpnConfigForConnect(context: Context, fp: String): ConnectFetchResult {
        repo.clearTunnelApiBase()
        repo.useApiBase(repo.getPublicServerUrl())
        repo.invalidateApiClient()

        var vpnConfig: VpnConfig? = null
        var apiError: String? = null
        var accessDenied = false
        var publicFailed = false

        coroutineScope {
            val regJob = async {
                runCatching {
                    repo.getApi().registerDevice(
                        DeviceRegisterRequest(repo.getDeviceDisplayName(), "android", fp, null, null),
                    )
                }.getOrNull()
            }
            val hashesJob = async {
                runCatching { repo.getApi().getVpnHashes() }.getOrNull()
            }

            val regRes = regJob.await()
            if (regRes != null) {
                when (regRes.code()) {
                    402, 403 -> {
                        accessDenied = true
                        apiError = parseError(regRes.errorBody()?.string() ?: "")
                            ?: subscriptionRequiredMessage()
                        return@coroutineScope
                    }
                }
                if (regRes.isSuccessful) {
                    val candidate = regRes.body()!!
                    if (isConfigConnectable(candidate)) {
                        vpnConfig = candidate
                        repo.saveSessionDeviceId(candidate.device_id)
                        _sessionDeviceId.value = candidate.device_id
                        repo.cacheVpnConfig(Gson().toJson(candidate))
                    } else {
                        apiError = "Сервер вернул некорректный WireGuard-конфиг. Обновите данные и повторите."
                        publicFailed = true
                    }
                } else if (regRes.code() != 0) {
                    apiError = parseError(regRes.errorBody()?.string() ?: "") ?: "Ошибка регистрации устройства"
                    publicFailed = true
                }
            } else {
                publicFailed = true
            }

            if (vpnConfig == null && !accessDenied) {
                runCatching {
                    val cfgRes = repo.getApi().getConfig(fp)
                    if (cfgRes.isSuccessful) {
                        val candidate = cfgRes.body()!!
                        if (isConfigConnectable(candidate)) {
                            vpnConfig = candidate
                            repo.cacheVpnConfig(Gson().toJson(candidate))
                        } else {
                            apiError = "Сервер вернул некорректный WireGuard-адрес. Повторите обновление профиля."
                            publicFailed = true
                        }
                    } else if (cfgRes.code() == 402) {
                        apiError = parseError(cfgRes.errorBody()?.string() ?: "")
                            ?: subscriptionRequiredMessage()
                        accessDenied = true
                    } else {
                        publicFailed = true
                    }
                }.onFailure {
                    publicFailed = true
                    apiError = apiError ?: it.message
                }
            }

            hashesJob.await()?.let { hres ->
                if (hres.isSuccessful && vpnConfig != null) {
                    vpnConfig = mergeHashesIntoConfig(hres, fp, vpnConfig!!)
                }
            }
        }

        if (!accessDenied && vpnConfig == null && (publicFailed || repo.isOnMobileData())) {
            if (runEphemeralApiBootstrap(context, force = true)) {
                val cached = loadCachedVpnConfig()
                vpnConfig = cached?.takeIf { isConfigConnectable(it) }
                if (vpnConfig != null) {
                    repo.mergeSavedHashesIntoCachedConfig()
                    vpnConfig = loadCachedVpnConfig()?.takeIf { isConfigConnectable(it) }
                }
            }
        }

        if (vpnConfig == null) {
            vpnConfig = loadCachedVpnConfig()?.takeIf { isConfigConnectable(it) }
        }
        if (vpnConfig == null && repo.hasMainVpnServerHashes()) {
            ensureVpnConfigRestored(context)
            vpnConfig = loadCachedVpnConfig()?.takeIf { isConfigConnectable(it) }
        }

        return ConnectFetchResult(vpnConfig, apiError, accessDenied)
    }

    private suspend fun mergeHashesIntoConfig(
        hres: Response<VpnHashesResponse>,
        fp: String,
        vpnConfig: VpnConfig,
    ): VpnConfig {
        if (!hres.isSuccessful) return vpnConfig
        val body = hres.body()
        val hashItems = body?.toHashItems().orEmpty()
        if (hashItems.isNotEmpty()) {
            repo.saveHashItems(hashItems)
            clearBootstrapIfServerHashesReady(hashItems)
        }
        val serverHashes = hashItems.activeServerHashes().map { it.hash }
        if (serverHashes.isEmpty()) return vpnConfig
        var cfg = vpnConfig.copy(vk_hashes = serverHashes.take(HashChannelHelper.MAX_HASHES))
        repo.cacheVpnConfig(Gson().toJson(cfg))
        if (serverHashes.size < HashChannelHelper.MAX_HASHES) {
            runCatching {
                repo.getApi().requestHashRefresh(ConnectRequest(fp, "android"))
            }
        }
        return cfg
    }

    /** Скачать список хешей с сервера; bootstrap убрать только при ≥1 активном серверном хеше. */
    private suspend fun syncServerHashes(preferPublicOnly: Boolean = false): List<HashItemDto> {
        val result = repo.fetchAndSaveHashItems(preferPublicOnly = preferPublicOnly)
        if (result.isFailure) {
            Log.w("MainViewModel", "syncServerHashes: ${result.exceptionOrNull()?.message}")
            return repo.getSavedHashItems()
        }
        val items = result.getOrDefault(emptyList())
        clearBootstrapIfServerHashesReady(items)
        return items
    }

    private var tunnelSyncWatchJob: Job? = null
    private var backendSyncJob: Job? = null
    private var resumeProfileJob: Job? = null
    private var connectJob: Job? = null
    private var disconnectJob: Job? = null
    /** До завершения VpnBackendSync не дергаем overlay из polling. */
    private var backendSyncCompleted: Boolean
        get() = VpnSessionState.backendSyncCompleted
        set(value) { VpnSessionState.backendSyncCompleted = value }

    private fun flushPendingHashFailures() {
        if (pendingHashFailures.isEmpty() || !repo.isLoggedIn()) return
        if (!repo.allowsBackgroundConfigSync()) return
        val batch = mutableListOf<Triple<String, String, String>>()
        while (true) {
            val item = pendingHashFailures.poll() ?: break
            batch.add(item)
        }
        if (batch.isEmpty()) return
        hashFailureFlushJob?.cancel()
        hashFailureFlushJob = viewModelScope.launch {
            repo.reportHashFailuresBatch(batch)
                .onFailure { e ->
                    batch.forEach { pendingHashFailures.add(it) }
                    DebugLog.w("MainViewModel", "hash failure batch: ${e.message}")
                }
        }
    }
    private var lastTunnelAttachAtMs = 0L
    /** Первое подключение туннеля — sync/theme. Resume attach не должен дёргать WG overlay. */
    private fun onVpnTunnelReady(vpnConfig: VpnConfig? = null, initialConnect: Boolean = true) {
        if (_vpnState.value == VpnState.DISCONNECTING) return
        if (silentBootstrapSync) return
        if (WdttTunnelManager.isBootstrapMode() && !bootstrapVpnMode) return
        val now = System.currentTimeMillis()
        if (!initialConnect) {
            if (now - lastTunnelAttachAtMs < 5_000L) return
            lastTunnelAttachAtMs = now
            if (_vpnState.value != VpnState.CONNECTED) {
                _vpnState.value = VpnState.CONNECTED
            }
            if (!bootstrapVpnMode && repo.isLoggedIn()) {
                watchTunnelDataSyncFromCache()
            }
            return
        }
        if (now - lastTunnelAttachAtMs < 3_000L) return
        lastTunnelAttachAtMs = now
        val wgAddr = vpnConfig?.wg_address?.takeIf { it.isNotBlank() }
            ?: loadCachedVpnConfig()?.wg_address?.takeIf { it.isNotBlank() }
            ?: WdttTunnelManager.lastWgAddress()
        repo.setTunnelApiFromWgAddress(wgAddr)
        repo.invalidatePublicReachabilityCache()
        restoreCachedThemeToUi()
        if (!bootstrapVpnMode && repo.isLoggedIn()) {
            watchTunnelDataSyncFromCache()
        }
    }

    /**
     * После tunnelReady — явная синхронизация (как при login через bootstrap),
     * через proxy/direct bind, без overlay и без пассивного ожидания VpnBackendSync.
     */
    private fun watchTunnelDataSyncFromCache() {
        tunnelSyncWatchJob?.cancel()
        tunnelSyncWatchJob = viewModelScope.launch {
            restoreCachedProfileToUi()
            restoreCachedThemeToUi()
            refreshHashState()

            if (!VpnSessionState.tunnelDataSyncCompleted) {
                if (repo.isOnMobileData()) {
                    repo.ensureTunnelApiProxy()
                }
                var ok = false
                repeat(4) { attempt ->
                    if (ok || _vpnState.value == VpnState.DISCONNECTING) return@repeat
                    if (attempt == 0) delay(2_000) else delay(1_500)
                    if (!WdttTunnelManager.tunnelReady.value || !SilentVpnService.isRunning) return@launch
                    ok = runCatching { repo.syncAllViaTunnel() }.getOrDefault(false)
                    if (ok) {
                        VpnSessionState.tunnelDataSyncCompleted = true
                        VpnSessionState.backendSyncCompleted = true
                        DebugLog.i("MainViewModel", "main VPN data sync OK (attempt ${attempt + 1})")
                    } else {
                        DebugLog.w("MainViewModel", "main VPN data sync failed (attempt ${attempt + 1})")
                    }
                }
                backendSyncCompleted = ok
            } else {
                backendSyncCompleted = true
                if (!repo.isPublicBackendReachable()) {
                    repo.pullAfterTunnelReady()
                }
            }

            restoreCachedProfileToUi()
            restoreCachedThemeToUi(refreshFromSync = true)
            refreshHashState()
            flushPendingHashFailures()
            repo.fetchProfileLiveViaUser().getOrNull()?.let { applyServerProfile(it) }
            ConfigSyncCoordinator.tickNow(repo, appContext, configSyncListener)
            seedConfigSyncRevision()
        }
    }

    private var updateCheckInFlight = false

    /** OTA: без VPN — public HTTPS; при VPN на Wi‑Fi — через tunnel/proxy. */
    fun checkForAppUpdate() {
        if (updateCheckInFlight) return
        updateCheckInFlight = true
        viewModelScope.launch {
            try {
                val version = com.silent.vpn.BuildConfig.VERSION_NAME
                val vpnUp = SilentVpnService.isRunning &&
                    WdttTunnelManager.tunnelReady.value &&
                    !WdttTunnelManager.isBootstrapMode()

                if (vpnUp && repo.allowsBackgroundConfigSync()) {
                    val ok = runCatching {
                        repo.withRoutineBackendApi {
                            val res = repo.getApi().checkUpdate("android", version)
                            if (!res.isSuccessful) {
                                DebugLog.w("MainViewModel", "checkUpdate HTTP ${res.code()} via tunnel")
                                return@withRoutineBackendApi false
                            }
                            val body = res.body()
                            if (body?.available == true) {
                                _updateInfo.value = body
                                updateApiBaseUrl = repo.getServerUrl().trimEnd('/')
                                DebugLog.i("MainViewModel", "checkUpdate: available ${body.version} via tunnel")
                            } else {
                                _updateInfo.value = null
                                DebugLog.i("MainViewModel", "checkUpdate: up to date v=$version via tunnel")
                            }
                            true
                        }
                    }.getOrDefault(false)
                    if (ok) return@launch
                }

                if (!vpnUp) {
                    val bases = listOf(
                        repo.getPublicServerUrl().trimEnd('/'),
                        "https://${SilentRepository.DEFAULT_SERVER_HOST}",
                    ).distinct()
                    for (base in bases) {
                        if (runCatching { tryCheckUpdateOnBase(base, version) }.getOrDefault(false)) break
                    }
                } else {
                    DebugLog.w("MainViewModel", "checkUpdate skipped: VPN up, tunnel check failed")
                }
            } catch (e: Exception) {
                DebugLog.w("MainViewModel", "checkUpdate: ${e.message}")
            } finally {
                updateCheckInFlight = false
            }
        }
    }

    /**
     * Экран «Сессии»: поллинг профиля с сервера (через tunnel proxy при VPN — без overlay).
     */
    fun setSessionsScreenActive(active: Boolean) {
        profilePollJob?.cancel()
        profilePollJob = null
        if (!active || repo.isOnMobileData()) return
        profilePollJob = viewModelScope.launch {
            while (true) {
                if (!sessionsFetchInFlight) {
                    sessionsFetchInFlight = true
                    val ok = runCatching { fetchProfileNow(force = true) }.getOrDefault(false)
                    if (!ok && repo.isOnMobileData() && SilentVpnService.isRunning) {
                        DebugLog.w("MainViewModel", "sessions poll: live fetch failed (mobile+VPN)")
                    }
                    sessionsFetchInFlight = false
                }
                delay(SESSIONS_POLL_MS)
            }
        }
    }

    /** Профиль приходит из initial sync при connect + кеша — без периодических overlay. */
    fun setVpnProfilePolling(active: Boolean) {
        // No-op: периодический поллинг убран, чтобы не дёргать WG overlay.
    }

    /** Главный экран: одна проверка OTA при открытии (только без VPN). */
    fun setUpdatePolling(active: Boolean) {
        if (active) checkForAppUpdate()
    }

    private suspend fun tryCheckUpdateOnBase(base: String, version: String): Boolean {
        repo.useApiBase(base)
        val res = repo.getApi().checkUpdate("android", version)
        if (!res.isSuccessful) {
            DebugLog.w("MainViewModel", "checkUpdate HTTP ${res.code()} on $base")
            return false
        }
        val body = res.body()
        if (body?.available == true) {
            _updateInfo.value = body
            updateApiBaseUrl = base.trimEnd('/')
            DebugLog.i("MainViewModel", "checkUpdate: available ${body.version} on $base")
        } else {
            _updateInfo.value = null
            DebugLog.i("MainViewModel", "checkUpdate: up to date v=$version on $base")
        }
        return true
    }

    fun downloadAndInstallUpdate(context: Context, onInstallReady: (Intent) -> Unit) {
        val info = _updateInfo.value ?: return
        if (_updateDownloading.value) return
        val downloadPath = info.download_url ?: return
        viewModelScope.launch {
            _updateDownloading.value = true
            _updateProgress.value = 0
            try {
                val base = repo.resolveUpdateDownloadBase(updateApiBaseUrl)
                val url = repo.joinUpdateUrl(base, downloadPath)
                DebugLog.i("MainViewModel", "update download url=$url overlay=${repo.needsOverlayForUpdateDownload(base)}")
                val download: suspend () -> java.io.File = {
                    AppUpdateManager.downloadApk(
                        context,
                        url,
                        info.filename ?: "update.apk",
                        repo.buildDownloadClient(),
                    ) { pct -> _updateProgress.value = pct }
                }
                val file = if (repo.needsOverlayForUpdateDownload(base)) {
                    repo.withTunnelApiForUpdateDownload { download() }
                } else {
                    download()
                }
                onInstallReady(AppUpdateManager.installApk(context, file, fromActivity = true))
            } catch (e: Exception) {
                DebugLog.e("MainViewModel", "update download failed: ${e.message}")
                _vpnError.value = "Ошибка загрузки обновления: ${e.message}"
            } finally {
                _updateDownloading.value = false
            }
        }
    }

    private fun loadProfile() {
        viewModelScope.launch {
            runCatching { fetchProfileNow() }
                .onFailure { e -> DebugLog.w("MainViewModel", "loadProfile: ${e.message}") }
        }
    }

    /** До входа: API через overlay, если поднят bootstrap-VPN (приложение вне WG). */
    private fun needsPreLoginApiOverlay(): Boolean {
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) return false
        if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) return false
        // Вся bootstrap-сессия (включая registerDevice после saveTokens)
        if (bootstrapVpnMode) return true
        return !repo.isLoggedIn()
    }

    private suspend fun <T> withBootstrapBackendApi(block: suspend () -> T): T {
        if (isBootstrapAuthVpnActive()) {
            repo.ensureBootstrapTunnelApi()
            return block()
        }
        if (needsPreLoginApiOverlay()) {
            if (!bootstrapVpnMode && _screen.value == AppScreen.LOGIN) {
                bootstrapVpnMode = true
            }
            return WdttTunnelManager.withApiOverlay {
                repo.useApiBase(WdttTunnelManager.tunnelApiBase())
                repo.invalidateApiClient()
                block()
            }
        }
        return block()
    }

    /** Bootstrap VPN для входа / регистрации / сброса пароля на мобильном интернете. */
    private fun isBootstrapAuthVpnActive(): Boolean =
        WdttTunnelManager.isBootstrapMode() &&
            WdttTunnelManager.tunnelReady.value &&
            SilentVpnService.isRunning &&
            (bootstrapVpnMode || _screen.value == AppScreen.LOGIN)

    private fun preLoginApiBases(): List<String> {
        if (
            _screen.value == AppScreen.LOGIN &&
            SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value
        ) {
            ensureTunnelApiBaseForLogin()
            return listOf(WdttTunnelManager.tunnelApiBase())
        }
        if (bootstrapVpnMode && WdttTunnelManager.tunnelReady.value && SilentVpnService.isRunning) {
            ensureTunnelApiBaseForLogin()
            return listOf(WdttTunnelManager.tunnelApiBase())
        }
        if (needsPreLoginApiOverlay()) {
            return listOf(WdttTunnelManager.tunnelApiBase())
        }
        if (bootstrapVpnMode && !SilentRepository.APP_EXCLUDED_FROM_VPN) {
            val gw = repo.wgGatewayFromAddress(WdttTunnelManager.lastWgAddress())
            if (gw != null) return listOf("http://$gw:8000")
        }
        return repo.apiBaseCandidates(WdttTunnelManager.lastWgAddress())
    }

    /** Автоподключение bootstrap VPN на экране входа (хеш зашит в BuildConfig). */
    fun ensureBootstrapForAuthFlow(context: Context) {
        if (_bootstrapExpired.value) return
        reconcileLoginBootstrapSession(context)
        if (!isHashReady()) return
        if (bootstrapVpnMode && SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) return
        if (_vpnState.value != VpnState.CONNECTING && !bootstrapConnectingInternal) {
            ensureBootstrapVpn(context)
        }
    }

    /**
     * Синхронизировать UI входа с реально работающим bootstrap-VPN.
     * ViewModel может пересоздаться, а FGS+туннель остаются — без этого UI «отключается».
     */
    fun reconcileLoginBootstrapSession(context: Context) {
        if (_bootstrapExpired.value) return
        if (repo.isLoggedIn()) {
            _bootstrapReady.value = false
            return
        }
        val ctx = context.applicationContext
        val serviceUp = SilentVpnService.isRunning
        val tunnelUp = WdttTunnelManager.tunnelReady.value
        val bootstrapTunnel = WdttTunnelManager.isBootstrapMode()

        if (serviceUp && tunnelUp && isHashReady() && (bootstrapTunnel || _screen.value == AppScreen.LOGIN)) {
            bootstrapVpnMode = true
            bootstrapContext = ctx
            if (_vpnState.value != VpnState.CONNECTED) {
                _vpnState.value = VpnState.CONNECTED
                onVpnTunnelReady(initialConnect = false)
            }
            WdttTunnelManager.lastWgAddress()?.takeIf { it.isNotBlank() }?.let {
                repo.setTunnelApiFromWgAddress(it)
            } ?: run {
                if (bootstrapTunnel) repo.ensureBootstrapTunnelApi()
            }
            startBootstrapSessionTimeout(
                ctx,
                forceNewDeadline = bootstrapDeadlineMs <= System.currentTimeMillis(),
            )
            DebugLog.i("MainViewModel", "reconcileLoginBootstrapSession: bootstrap VPN active")
        } else if (!serviceUp && bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            bootstrapVpnMode = false
            cancelBootstrapSessionTimeout()
            _vpnState.value = VpnState.DISCONNECTED
        }
        updateBootstrapReadyFlag()
    }

    private fun updateBootstrapReadyFlag() {
        _bootstrapReady.value = !repo.isLoggedIn() &&
            bootstrapVpnMode &&
            SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            _vpnState.value == VpnState.CONNECTED
    }

    private suspend fun fetchProfileNow(force: Boolean = false): Boolean {
        if (
            _vpnState.value == VpnState.CONNECTING ||
            _vpnState.value == VpnState.DISCONNECTING ||
            (!force && WdttTunnelManager.isApiOverlayActive())
        ) {
            return !force && _profile.value != null
        }
        if (
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            !bootstrapVpnMode &&
            !WdttTunnelManager.isBootstrapMode()
        ) {
            if (!force && _profile.value != null) return true
            if (
                !force &&
                (WdttTunnelManager.isWorkerRampUpActive() || WdttTunnelManager.isApiOverlayActive())
            ) {
                return _profile.value != null
            }
            if (force) {
                return repo.fetchProfileLive().fold(
                    onSuccess = { p ->
                        applyServerProfile(p)
                        p.vk_user_id?.let { repo.saveVkUserId(it) }
                        true
                    },
                    onFailure = { e ->
                        DebugLog.w("MainViewModel", "fetchProfile force: ${e.message}")
                        false
                    },
                )
            }
            return runCatching {
                repo.withBackendApi { tryFetchProfileViaRepoApi() }
            }.getOrDefault(false) || _profile.value != null
        }
        if (SilentVpnService.isRunning && !bootstrapVpnMode && !force) {
            return _profile.value != null
        }
        if (
            SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            bootstrapVpnMode
        ) {
            return withBootstrapBackendApi {
                tryFetchProfileOnBase(WdttTunnelManager.tunnelApiBase()) || _profile.value != null
            }
        }
        val wg = WdttTunnelManager.lastWgAddress()
        for (base in repo.apiBaseCandidates(wg)) {
            if (tryFetchProfileOnBase(base)) return true
        }
        return !force && _profile.value != null
    }

    private suspend fun tryFetchProfileViaRepoApi(): Boolean {
        try {
            val res = repo.getApi().getProfile()
            if (res.isSuccessful) {
                val p = res.body()!!
                applyServerProfile(p)
                repo.saveCachedProfile(p)
                p.vk_user_id?.let { repo.saveVkUserId(it) }
                DebugLog.i("MainViewModel", "fetchProfile OK via ${repo.getServerUrl()}")
                return true
            }
            if (res.code() == 401) {
                logout()
                return false
            }
        } catch (e: Exception) {
            DebugLog.w("MainViewModel", "fetchProfile: ${e.message}")
        }
        return false
    }

    private suspend fun tryFetchProfileOnBase(base: String): Boolean {
        try {
            repo.useApiBase(base)
            val res = repo.getApi().getProfile()
            if (res.isSuccessful) {
                val p = res.body()!!
                applyServerProfile(p)
                repo.saveCachedProfile(p)
                p.vk_user_id?.let { repo.saveVkUserId(it) }
                DebugLog.i("MainViewModel", "fetchProfile OK via $base")
                runCatching {
                    val themeRes = repo.getApi().getTheme()
                    if (themeRes.isSuccessful) _theme.value = themeRes.body()
                }
                return true
            }
            if (res.code() == 401) {
                logout()
                return false
            }
        } catch (e: Exception) {
            DebugLog.w("MainViewModel", "fetchProfile on $base: ${e.message}")
        }
        return false
    }

    private fun loadTheme() {
        viewModelScope.launch {
            restoreCachedThemeToUi()
            if (SilentVpnService.isRunning && !bootstrapVpnMode) {
                // Тема на основном VPN — только в syncAllViaTunnel (один overlay), не отдельным запросом.
                return@launch
            }
            runCatching {
                val res = repo.getApi().getTheme()
                if (res.isSuccessful) {
                    res.body()?.let {
                        _theme.value = it
                        repo.saveCachedTheme(it)
                    }
                }
            }
        }
    }

    fun clearForgotSent() {
        _forgotSent.value = false
    }

    fun forgotPassword(email: String) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            _forgotSent.value = false
            try {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _authError.value = "Сначала подключитесь для входа (шаг 1)"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                awaitTunnelApiReady()
                val res = withBootstrapBackendApi {
                    repo.getApi().forgotPassword(ForgotPasswordRequest(email))
                }
                if (!res.isSuccessful) {
                    _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Ошибка отправки"
                    return@launch
                }
                _forgotSent.value = true
                refreshBootstrapCountdownNow()
                // Таймер не перезапускаем — те же 2 мин с шага 1.
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка отправки"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
                if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
                    restartBootstrapTimerIfNeeded()
                }
            }
        }
    }

    fun login(email: String, password: String, rememberMe: Boolean, activity: ComponentActivity? = null) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            _statusMsg.value = "Вход…"
            try {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _authError.value = "Сначала дождитесь зелёной надписи «Канал готов»"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                if (!WdttTunnelManager.tunnelReady.value) {
                    _authError.value = "VPN ещё не готов. Подождите 3–5 секунд"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                ensureTunnelApiBaseForLogin()
                val ctx = activity?.applicationContext ?: appContext
                val loginDevice = LoginDeviceInfo(
                    device_fingerprint = repo.startNewSession(),
                    device_type = "android",
                    device_name = repo.getDeviceDisplayName(),
                )
                var loginSucceeded = false
                var offerSavePassword = false
                withBootstrapBackendApi {
                    val res = loginAttempt(email, password, loginDevice)
                    if (!res.isSuccessful) {
                        _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Неверный логин или пароль"
                        restartBootstrapTimerIfNeeded()
                    } else {
                        val tokens = res.body()!!
                        repo.saveTokens(tokens.access_token, tokens.refresh_token)
                        repo.saveRememberMe(email, password, rememberMe)
                        if (!openLoginSession()) {
                            if (repo.isLoggedIn()) {
                                syncLoginDataViaBootstrapTunnel(registerIfNeeded = true)
                                loginSucceeded = true
                            }
                        } else {
                            if (!syncLoginDataViaBootstrapTunnel(registerIfNeeded = false)) {
                                _vpnError.value = "Профиль не загрузился. Включите VPN на главном экране."
                            } else {
                                DebugLog.i("MainViewModel", "login sync OK profile=${_profile.value?.email}")
                            }
                            loginSucceeded = true
                            offerSavePassword = true
                        }
                    }
                }
                if (loginSucceeded) {
                    disconnectBootstrapVpn(ctx)
                    goToMain(skipProfileFetch = true)
                    startConfigSync()
                    if (offerSavePassword) {
                        activity?.let { CredentialHelper.offerSavePassword(it, email, password) }
                    }
                }
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка входа"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
                if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
                    restartBootstrapTimerIfNeeded()
                }
            }
        }
    }

    private suspend fun loginAttempt(
        email: String,
        password: String,
        device: LoginDeviceInfo? = null,
    ): retrofit2.Response<com.silent.vpn.data.TokenResponse> {
        awaitTunnelApiReady()
        val bases = preLoginApiBases()
        if (bases.isEmpty()) {
            throw Exception("VPN ещё не готов. Дождитесь «Канал готов» на шаге 1.")
        }
        var lastError: Exception? = null
        repeat(3) { attempt ->
            for (base in bases) {
                try {
                    repo.useApiBase(base)
                    DebugLog.i("MainViewModel", "login try API base=$base (attempt ${attempt + 1})")
                    val res = repo.getApi().login(LoginRequest(email, password, device))
                    DebugLog.i("MainViewModel", "login HTTP ${res.code()} on $base")
                    if (res.isSuccessful || res.code() in 400..499) return res
                    lastError = Exception(parseError(res.errorBody()?.string() ?: "") ?: "HTTP ${res.code()}")
                } catch (e: Exception) {
                    lastError = e
                    DebugLog.w("MainViewModel", "login failed on $base: ${e.message}")
                }
            }
            if (attempt < 2) delay(700)
        }
        throw lastError ?: Exception("Не удалось связаться с сервером. Проверьте VPN и попробуйте снова.")
    }

    private suspend fun awaitTunnelApiReady() {
        repeat(25) {
            if (ensureTunnelApiBaseForLogin()) return
            delay(200)
        }
        ensureTunnelApiBaseForLogin()
    }

    /** Без debounce onVpnTunnelReady — нужен сразу перед login/register. */
    private fun ensureTunnelApiBaseForLogin(): Boolean {
        if (!WdttTunnelManager.tunnelReady.value) return false
        if (WdttTunnelManager.isBootstrapMode()) {
            return repo.ensureBootstrapTunnelApi()
        }
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) {
            repo.useApiBase(WdttTunnelManager.tunnelApiBase())
            repo.invalidateApiClient()
            return true
        }
        val wgAddr = WdttTunnelManager.lastWgAddress()?.takeIf { it.isNotBlank() } ?: return false
        repo.setTunnelApiFromWgAddress(wgAddr)
        return true
    }

    fun register(email: String, password: String, rememberMe: Boolean) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            try {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _authError.value = "Сначала подключитесь для входа (шаг 1)"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                awaitTunnelApiReady()
                withBootstrapBackendApi {
                    val res = registerAttempt(email, password)
                    if (!res.isSuccessful) {
                        _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Ошибка регистрации"
                        restartBootstrapTimerIfNeeded()
                    } else {
                        repo.saveRememberMe(email, password, rememberMe)
                        _regEmail.value = email
                        _regDone.value = true
                        refreshBootstrapCountdownNow()
                    }
                }
                // Таймер не перезапускаем — те же 2 мин с шага 1, потом VPN отключится.
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка регистрации"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
                if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
                    restartBootstrapTimerIfNeeded()
                }
            }
        }
    }

    private suspend fun registerAttempt(email: String, password: String): retrofit2.Response<Map<String, String>> {
        awaitTunnelApiReady()
        val bases = preLoginApiBases()
        if (bases.isEmpty()) {
            throw Exception("VPN ещё не готов. Дождитесь «Канал готов» на шаге 1.")
        }
        var lastError: Exception? = null
        for (base in bases) {
            try {
                repo.useApiBase(base)
                val res = repo.getApi().register(RegisterRequest(email, password))
                DebugLog.i("MainViewModel", "register HTTP ${res.code()} on $base")
                if (res.isSuccessful || res.code() in 400..499) return res
                lastError = Exception(parseError(res.errorBody()?.string() ?: "") ?: "HTTP ${res.code()}")
            } catch (e: Exception) {
                lastError = e
                DebugLog.w("MainViewModel", "register failed on $base: ${e.message}")
            }
        }
        throw lastError ?: Exception("Не удалось связаться с сервером. Проверьте VPN и попробуйте снова.")
    }

    fun clearAuthError() { _authError.value = null }
    fun clearVpnError() { _vpnError.value = null }
    fun showError(msg: String) { _vpnError.value = msg }
    fun dismissRegDone() { _regDone.value = false; _regEmail.value = "" }

    fun goToMain(skipProfileFetch: Boolean = false) {
        _screen.value = AppScreen.MAIN
        startConfigSync()
        if (!skipProfileFetch && _profile.value == null) {
            loadProfile()
        }
    }

    override fun onCleared() {
        stopConfigSync()
        com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener = null
        com.silent.vpn.sync.VpnDataSyncBridge.onCycleCompleted = null
        super.onCleared()
    }

    private suspend fun disconnectBootstrapVpn(context: Context) {
        if (!bootstrapVpnMode) return
        cancelBootstrapSessionTimeout()
        bootstrapDeadlineMs = 0L
        WdttTunnelManager.prepareForShutdown()
        stopVpnLocally(context)
        WdttTunnelManager.stopAndAwait()
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        bootstrapVpnMode = false
        bootstrapContext = null
        _vpnState.value = VpnState.DISCONNECTED
        repo.clearTunnelApiBase()
        clearBootstrapHashAfterLogin()
        _statusMsg.value = "Интернет отключён. VPN включайте на главном экране."
        updateBootstrapReadyFlag()
    }

    private fun startBootstrapSessionTimeout(context: Context, forceNewDeadline: Boolean = false) {
        if (!bootstrapVpnMode) return
        val now = System.currentTimeMillis()
        if (forceNewDeadline || bootstrapDeadlineMs <= now) {
            bootstrapDeadlineMs = now + BOOTSTRAP_SESSION_MS
        }
        bootstrapContext = context.applicationContext
        refreshBootstrapCountdownNow()
        if (bootstrapTimeoutJob?.isActive == true) return
        bootstrapTimeoutJob = viewModelScope.launch {
            while (bootstrapVpnMode && !repo.isLoggedIn()) {
                val leftSec = ((bootstrapDeadlineMs - System.currentTimeMillis()) / 1000L).toInt()
                if (leftSec <= 0) break
                refreshBootstrapCountdownNow()
                delay(1000)
            }
            if (bootstrapVpnMode && !repo.isLoggedIn()) {
                expireBootstrapSession()
            }
        }
    }

    private fun refreshBootstrapCountdownNow() {
        if (!bootstrapVpnMode || bootstrapDeadlineMs <= 0L) {
            _bootstrapSecondsLeft.value = null
            updateBootstrapReadyFlag()
            return
        }
        val leftSec = ((bootstrapDeadlineMs - System.currentTimeMillis()) / 1000L).toInt()
        if (leftSec <= 0) {
            _bootstrapSecondsLeft.value = null
            updateBootstrapReadyFlag()
            return
        }
        _bootstrapSecondsLeft.value = leftSec
        val mm = leftSec / 60
        val ss = leftSec % 60
        _statusMsg.value = when {
            _regDone.value ->
                "Подтвердите email (браузер/почта). VPN ещё %d:%02d".format(mm, ss)
            _forgotSent.value ->
                "Откройте ссылку из письма (браузер/почта). VPN ещё %d:%02d".format(mm, ss)
            else ->
                "Канал готов. Осталось %d:%02d — войдите или зарегистрируйтесь".format(mm, ss)
        }
        updateBootstrapReadyFlag()
    }

    private fun cancelBootstrapSessionTimeout() {
        bootstrapTimeoutJob?.cancel()
        bootstrapTimeoutJob = null
        _bootstrapSecondsLeft.value = null
        updateBootstrapReadyFlag()
    }

    private fun resetBootstrapDeadline() {
        cancelBootstrapSessionTimeout()
        bootstrapDeadlineMs = 0L
    }

    private fun expireBootstrapSession() {
        val ctx = bootstrapContext ?: return
        if (!bootstrapVpnMode || repo.isLoggedIn()) return
        DebugLog.i("MainViewModel", "bootstrap session expired (${BOOTSTRAP_SESSION_MS / 1000}s)")
        resetBootstrapDeadline()
        stopVpnLocally(ctx)
        bootstrapVpnMode = false
        bootstrapContext = null
        repo.clearTunnelApiBase()
        _vpnState.value = VpnState.DISCONNECTED
        _statusMsg.value = BOOTSTRAP_EXPIRED_MSG
        _bootstrapExpired.value = true
        updateBootstrapReadyFlag()
    }

    /** Остановить VPN и сервисы перед полным закрытием приложения с экрана входа. */
    fun shutdownBeforeExit(context: Context) {
        cancelBootstrapSessionTimeout()
        resetBootstrapDeadline()
        bootstrapVpnMode = false
        bootstrapContext = null
        bootstrapConnectingInternal = false
        _bootstrapConnecting.value = false
        stopVpnLocally(context)
        repo.clearTunnelApiBase()
        _vpnState.value = VpnState.DISCONNECTED
        updateBootstrapReadyFlag()
    }

    /** Bootstrap VPN on login screen — reach backend through user's VK hash. */
    fun ensureBootstrapVpn(context: Context) {
        if (_bootstrapExpired.value) return
        if (repo.isLoggedIn() || !isHashReady()) return
        if (bootstrapConnectingInternal) return
        if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            bootstrapContext = context.applicationContext
            resumeBootstrapTimerIfNeeded()
            return
        }
        DebugLog.i("MainViewModel", "ensureBootstrapVpn start")
        viewModelScope.launch {
            bootstrapConnectingInternal = true
            _bootstrapConnecting.value = true
            _vpnError.value = null
            try {
                val boot = HashParser.extract(repo.getBootstrapHash().orEmpty())
                    ?: run {
                        _statusMsg.value = "Неверный bootstrap-хеш в сборке приложения."
                        return@launch
                    }
                val fp = repo.getOrCreatePreLoginFingerprint()
                val config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))

                if (config.vk_hashes.isEmpty()) {
                    _statusMsg.value = "Нет VK-хеша для bootstrap"
                    return@launch
                }
                bootstrapVpnMode = true
                bootstrapContext = context.applicationContext
                _bootstrapExpired.value = false
                _vpnState.value = VpnState.CONNECTING
                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_CONNECT
                    putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(config))
                    putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, true)
                }
                ContextCompat.startForegroundService(context, intent)
                repeat(60) {
                    delay(500)
                    if (_vpnState.value != VpnState.CONNECTING) return@launch
                    if (WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value) {
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady(config)
                        repo.ensureBootstrapTunnelApi()
                        startBootstrapSessionTimeout(context, forceNewDeadline = true)
                        return@launch
                    }
                }
                if (_vpnState.value == VpnState.CONNECTING) {
                    cancelBootstrapSessionTimeout()
                    stopVpnLocally(context)
                    bootstrapVpnMode = false
                    _vpnState.value = VpnState.DISCONNECTED
                    _statusMsg.value = WdttTunnelManager.lastError.value
                        ?: WdttTunnelManager.stats.value.takeIf { it.isNotBlank() }
                        ?: "Интернет через VPN не поднялся. Закройте приложение и запустите снова."
                }
            } catch (e: Exception) {
                Log.e("MainViewModel", "bootstrap VPN", e)
                cancelBootstrapSessionTimeout()
                stopVpnLocally(context)
                bootstrapVpnMode = false
                _vpnState.value = VpnState.DISCONNECTED
                _statusMsg.value = e.message ?: "Ошибка bootstrap VPN"
            } finally {
                bootstrapConnectingInternal = false
                _bootstrapConnecting.value = false
            }
        }
    }

    private fun restartBootstrapTimerIfNeeded() {
        resumeBootstrapTimerIfNeeded()
    }

    /** Продолжить отсчёт с того же дедлайна (шаг 2 → шаг 1). */
    private fun resumeBootstrapTimerIfNeeded() {
        val ctx = bootstrapContext ?: appContext
        if (bootstrapVpnMode && !repo.isLoggedIn()) {
            if (SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _vpnState.value = VpnState.CONNECTED
                }
                startBootstrapSessionTimeout(ctx, forceNewDeadline = false)
            }
            updateBootstrapReadyFlag()
        }
    }

    private suspend fun openLoginSession(): Boolean {
        val boot = repo.getBootstrapHash()
        val res = repo.getApi().registerDevice(
            DeviceRegisterRequest(repo.getDeviceDisplayName(), "android", repo.getDeviceFingerprint(), null, boot)
        )
        DebugLog.i("MainViewModel", "registerDevice HTTP ${res.code()}")
        if (res.isSuccessful) {
            val cfg = res.body()!!
            repo.saveSessionDeviceId(cfg.device_id)
            repo.cacheVpnConfig(Gson().toJson(cfg))
            _sessionDeviceId.value = cfg.device_id
            return true
        }
        val bodyStr = res.errorBody()?.string() ?: ""
        DebugLog.e("MainViewModel", "device/register HTTP ${res.code()}: ${bodyStr.take(200)}")
        if (res.code() == 402) {
            // Subscription expired — user is authenticated but has no active plan.
            // Don't clear tokens: let caller navigate to main with a renewal prompt.
            _vpnError.value = parseError(bodyStr)
                ?: "Пробный период закончился. Для продолжения оформите подписку."
            return false
        }
        _authError.value = parseError(bodyStr)
            ?: "Достигнут лимит устройств (3). Выйдите на другом устройстве."
        repo.clearSessionFingerprint()
        repo.clearTokens()
        restartBootstrapTimerIfNeeded()
        return false
    }

    fun logout(context: Context? = null) {
        viewModelScope.launch {
            val fp = if (repo.hasSessionFingerprint()) {
                runCatching { repo.getDeviceFingerprint() }.getOrNull()
            } else null

            if (_vpnState.value == VpnState.CONNECTED || _vpnState.value == VpnState.CONNECTING) {
                context?.let { stopVpnLocally(it) }
            }
            bootstrapVpnMode = false
            bootstrapContext = null
            cancelBootstrapSessionTimeout()

            if (fp != null && repo.getAccessToken() != null) {
                runCatching {
                    val res = repo.getApi().logoutSession(DisconnectRequest(fp))
                    if (!res.isSuccessful) {
                        Log.w("MainViewModel", "logout API ${res.code()}")
                    }
                }
            }

            repo.clearCachedProfile()  // сначала чистим кеш — до clearTokens, чтобы не было стейла
            repo.clearSessionFingerprint()
            repo.clearSessionDeviceId()
            repo.clearCachedVpnConfig()
            repo.clearSavedHashItems()
            repo.clearSyncRevisions()
            repo.clearTunnelApiBase()
            stopConfigSync()
            repo.clearTokens()
            _sessionDeviceId.value = null
            _profile.value = null
            _vpnState.value = VpnState.DISCONNECTED
            _screen.value = AppScreen.LOGIN
            restoreCachedThemeToUi()
            loadTheme()
            _authError.value = null
            _vpnError.value = null
            _regDone.value = false
            _forgotSent.value = false
        }
    }

    private fun stopVpnLocally(context: Context) {
        tunnelSyncWatchJob?.cancel()
        tunnelSyncWatchJob = null
        backendSyncJob?.cancel()
        backendSyncJob = null
        backendSyncCompleted = false
        lastTunnelAttachAtMs = 0L
        pendingHashFailures.clear()
        hashFailureFlushJob?.cancel()
        hashFailureFlushJob = null
        runCatching {
            val intent = Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            }
            context.startService(intent)
        }
        if (!SilentVpnService.isRunning) {
            WdttTunnelManager.stop()
        }
    }

    fun connect(context: Context) {
        SessionTrace.enter("MainViewModel.connect", "state=${_vpnState.value}")
        if (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.DISCONNECTING) {
            DebugLog.i("MainViewModel", "connect ignored: operation in progress")
            SessionTrace.exit("MainViewModel.connect", "busy")
            return
        }
        if (VpnSessionState.isActive()) {
            SessionTrace.mark("MainViewModel.connect", "attach existing session")
            DebugLog.i("MainViewModel", "connect attach — shared session already active")
            _vpnState.value = VpnState.CONNECTED
            _vpnError.value = null
            pendingConnectAfterSubscriptionRefresh = false
            attachExistingSession()
            SessionTrace.exit("MainViewModel.connect", "attached")
            return
        }
        if (_vpnState.value == VpnState.CONNECTED && SilentVpnService.isRunning) {
            SessionTrace.exit("MainViewModel.connect", "already connected")
            DebugLog.i("MainViewModel", "connect ignored: already connected")
            return
        }
        resumeProfileJob?.cancel()
        connectJob?.cancel()
        disconnectJob?.cancel()
        _vpnState.value = VpnState.CONNECTING
        _vpnError.value = null
        connectJob = viewModelScope.launch {
            DebugLog.i("MainViewModel", "connect() start")
            bootstrapVpnMode = false
            backendSyncCompleted = false
            VpnSessionState.resetBackendSync()
            if (VpnNetworkHelper.isOtherVpnActive(context)) {
                DebugLog.i("MainViewModel", "Подключение заменит другой активный VPN")
            }
            try {
            runCatching {
                restoreCachedProfileToUi()
                if (!hasVpnAccess() && repo.isOnMobileData() && !VpnSessionState.isActive()) {
                    runEphemeralApiBootstrap(context, force = true)
                    restoreCachedProfileToUi()
                }
                if (!hasVpnAccess()) {
                    pendingConnectAfterSubscriptionRefresh = true
                    _vpnError.value = subscriptionRequiredMessage()
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                val fp = runCatching { repo.getDeviceFingerprint() }.getOrElse {
                    if (repo.hasSessionFingerprint()) throw it
                    repo.startNewSession()
                }
                val cached = loadCachedVpnConfig()
                if (cached != null && isConfigConnectable(cached)) {
                    val config = wdttConnectConfig(resolveMainVpnConfig(cached))
                    if (WdttTunnelManager.running.value) {
                        _vpnState.value = VpnState.CONNECTED
                        pendingConnectAfterSubscriptionRefresh = false
                        attachExistingSession()
                        return@launch
                    }
                    if (android.net.VpnService.prepare(context) != null) {
                        _vpnError.value = "Нужно разрешение VPN"
                        _vpnState.value = VpnState.DISCONNECTED
                        return@launch
                    }
                    val connectIntent = VpnTileConnect.buildConnectIntentFromCache(context)
                    if (connectIntent == null) {
                        _vpnError.value = "Нет сохранённой конфигурации VPN"
                        _vpnState.value = VpnState.DISCONNECTED
                        return@launch
                    }
                    DebugLog.i(
                        "MainViewModel",
                        "connect device=${config.device_id.take(12)} n=${config.stream_count} vk=${config.vk_hashes.size}",
                    )
                    androidx.core.content.ContextCompat.startForegroundService(context, connectIntent)
                    waitForTunnelReady(context, config.stream_count)
                    return@launch
                }

                val fetch = fetchVpnConfigForConnect(context, fp)
                var vpnConfig = fetch.vpnConfig
                val apiError = fetch.apiError
                val accessDenied = fetch.accessDenied

                if (accessDenied) {
                    pendingConnectAfterSubscriptionRefresh = true
                    _vpnError.value = apiError ?: subscriptionRequiredMessage()
                    _vpnState.value = VpnState.DISCONNECTED
                    loadProfile()
                    return@launch
                }

                if (vpnConfig == null) {
                    DebugLog.e("MainViewModel", apiError ?: "no vpn config")
                    _vpnError.value = apiError
                        ?: "Не удалось восстановить VPN. Проверьте интернет и повторите."
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                if (!isConfigConnectable(vpnConfig!!)) {
                    _vpnError.value = when {
                        !repo.hasMainVpnServerHashes() && repo.resolveConnectVkHashes(vpnConfig!!.vk_hashes).isEmpty() ->
                            "Нет серверных хешей. Перезайдите в аккаунт."
                        vpnConfig!!.vk_hashes.isEmpty() -> "Нет VK-хеша. Введите хеш на экране входа."
                        !hasValidWgAddress(vpnConfig!!.wg_address) -> "Некорректный WireGuard-адрес от сервера. Обновите профиль и повторите."
                        else -> "Нет ключей WireGuard на сервере. Перезайдите в аккаунт."
                    }
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                val toConnect = wdttConnectConfig(resolveMainVpnConfig(vpnConfig!!))
                DebugLog.i(
                    "MainViewModel",
                    "connect device=${toConnect.device_id.take(12)} n=${toConnect.stream_count} vk=${toConnect.vk_hashes.size}",
                )
                launchVpnService(context, toConnect)
                pendingConnectAfterSubscriptionRefresh = false
                waitForTunnelReady(context, toConnect.stream_count)
            }.onFailure {
                DebugLog.e("MainViewModel", "connect failed", it)
                _vpnError.value = it.message ?: "Ошибка подключения"
                _vpnState.value = VpnState.DISCONNECTED
            }
            } catch (e: CancellationException) {
                DebugLog.w("MainViewModel", "connect cancelled")
                // Не рвать уже запущенный сервис (плитка / CONNECT в процессе).
                if (_vpnState.value == VpnState.CONNECTING && !SilentVpnService.isRunning) {
                    _vpnState.value = VpnState.DISCONNECTED
                }
                throw e
            }
        }
    }

    private fun loadCachedVpnConfig(): VpnConfig? {
        val cached = repo.getCachedVpnConfig() ?: return null
        val parsed = runCatching { Gson().fromJson(cached, VpnConfig::class.java) }.getOrNull() ?: return null
        if (repo.isLoggedIn() && parsed.device_id.startsWith("boot:")) {
            DebugLog.w("MainViewModel", "cached VPN config is bootstrap — ignore after login")
            return null
        }
        if (parsed.device_id != repo.getSessionDeviceId()) return null
        return parsed
    }

    private fun isConfigConnectable(config: VpnConfig): Boolean =
        repo.resolveConnectVkHashes(config.vk_hashes).isNotEmpty() &&
            config.wg_private_key.isNotBlank() &&
            config.server_public_key.isNotBlank() &&
            hasValidWgAddress(config.wg_address)

    private fun hasValidWgAddress(address: String): Boolean {
        val parts = address.trim().split("/")
        if (parts.size != 2) return false
        val prefix = parts[1].toIntOrNull() ?: return false
        if (prefix !in 0..32) return false
        val octets = parts[0].split(".")
        if (octets.size != 4) return false
        return octets.all { it.toIntOrNull()?.let { n -> n in 0..255 } == true }
    }

    private fun vpnConfigForWdtt(config: VpnConfig): VpnConfig {
        val hashes = repo.resolveConnectVkHashes(config.vk_hashes)
        return if (hashes.isNotEmpty()) config.copy(vk_hashes = hashes) else config
    }

    /**
     * Один CONNECT с полным n и всеми хешами (как proxy-turn-vk-android).
     * libclient каскадом: первая группа (~5 с) → WG; остальные добирают каналы в том же процессе.
     */
    private fun wdttConnectConfig(config: VpnConfig): VpnConfig {
        val filtered = vpnConfigForWdtt(config)
        val activeHashes = maxOf(
            filtered.vk_hashes.size,
            repo.getSavedHashItems().activeServerHashes().size,
            1,
        ).coerceAtMost(HashChannelHelper.MAX_HASHES)
        val workers = repo.resolveWorkersForLibclient(activeHashes)
        val hashes = HashChannelHelper.hashesForLibclient(filtered.vk_hashes, workers)
        val source = if (repo.hasMainVpnServerHashes()) "saved" else "cache"
        DebugLog.i("MainViewModel", "wdtt config: hashes=$source n=${hashes.size} workers=$workers")
        return filtered.copy(
            vk_hashes = hashes.ifEmpty { filtered.vk_hashes },
            stream_count = workers,
        )
    }

    private fun launchVpnService(context: Context, config: VpnConfig, forceBootstrap: Boolean = false) {
        val isBootstrap = forceBootstrap || bootstrapVpnMode
        val forService = if (isBootstrap) config else resolveMainVpnConfig(config)
        val wdttConfig = wdttConnectConfig(forService)
        val intent = Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(wdttConfig))
            putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, isBootstrap)
        }
        ContextCompat.startForegroundService(context, intent)
    }

    /** После входа основной VPN не должен стартовать с boot: device_id (иначе n=9, 1 хеш). */
    private fun resolveMainVpnConfig(config: VpnConfig): VpnConfig {
        if (!repo.isLoggedIn() || bootstrapVpnMode) return config
        if (!config.device_id.startsWith("boot:")) return config
        val sessionId = repo.getSessionDeviceId()?.takeIf { it.isNotBlank() && !it.startsWith("boot:") }
            ?: return config
        DebugLog.w("MainViewModel", "main VPN: boot device_id → ${sessionId.take(8)}")
        return config.copy(device_id = sessionId)
    }

    private suspend fun refreshVpnConfigInBackground(fp: String) {
        runCatching {
            repo.withBackendApi {
                applyRefreshVpnConfigDirect(fp)
            }
        }
    }

    private suspend fun applyRefreshVpnConfigDirect(fp: String) {
        var cfg = runCatching {
            val res = repo.getApi().getConfig(fp)
            if (res.isSuccessful) res.body() else null
        }.getOrNull()
        if (cfg == null) {
            val res = repo.getApi().registerDevice(
                DeviceRegisterRequest(repo.getDeviceDisplayName(), "android", fp, null, null),
            )
            if (!res.isSuccessful) return
            cfg = res.body()!!
        }
        repo.saveSessionDeviceId(cfg.device_id)
        _sessionDeviceId.value = cfg.device_id
        val hres = repo.getApi().getVpnHashes()
        if (hres.isSuccessful) {
            val body = hres.body()
            val hashItems = body?.toHashItems().orEmpty()
            if (hashItems.isNotEmpty()) {
                repo.saveHashItems(hashItems)
                clearBootstrapIfServerHashesReady(hashItems)
            }
            val serverHashes = hashItems.activeServerHashes().map { it.hash }
            if (serverHashes.isNotEmpty()) cfg = cfg.copy(vk_hashes = serverHashes)
        }
        repo.cacheVpnConfig(Gson().toJson(cfg))
        repo.mergeSavedHashesIntoCachedConfig()
    }

    /** WG поднимается за 3–5 с; ждём до 45 с (капча/сеть). */
    private suspend fun waitForTunnelReady(context: Context, @Suppress("UNUSED_PARAMETER") totalWorkers: Int) {
        repeat(225) {
            delay(200)
            if (_vpnState.value != VpnState.CONNECTING) return
            if (WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value) {
                _vpnState.value = VpnState.CONNECTED
                onVpnTunnelReady()
                return
            }
        }
        if (_vpnState.value != VpnState.CONNECTING) return
        if (WdttTunnelManager.tunnelReady.value) {
            _vpnState.value = VpnState.CONNECTED
            onVpnTunnelReady()
            return
        }
        val err = WdttTunnelManager.lastError.value
            ?: WdttTunnelManager.stats.value.takeIf { it.isNotBlank() }
            ?: "Таймаут: VPN не подключился"
        stopVpnLocally(context)
        withContext(Dispatchers.IO) {
            VpnConnectHelper.ensureCleanSlate(context, force = true)
        }
        _vpnError.value = err
        _vpnState.value = VpnState.DISCONNECTED
    }

    private fun markLocalDeviceOffline() {
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId() ?: return
        val p = _profile.value ?: return
        val updated = p.devices.map { d ->
            if (d.id == sid) d.copy(is_connected = false) else d
        }
        val connectedCount = updated.count { it.is_connected }
        _profile.value = p.copy(devices = updated, connected_count = connectedCount)
    }

    private fun markLocalDeviceOnline() {
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId() ?: return
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.map { d ->
            if (d.id == sid) d.copy(is_connected = true) else d
        }
        val connectedCount = updated.count { it.is_connected }
        _profile.value = p.copy(devices = updated, connected_count = connectedCount)
    }

    fun disconnect(context: Context) {
        SessionTrace.enter("MainViewModel.disconnect")
        if (_vpnState.value == VpnState.DISCONNECTING) {
            SessionTrace.exit("MainViewModel.disconnect", "already disconnecting")
            return
        }
        if (_vpnState.value == VpnState.DISCONNECTED && !SilentVpnService.isRunning) {
            SessionTrace.exit("MainViewModel.disconnect", "already off")
            pendingConnectAfterSubscriptionRefresh = false
            return
        }
        pendingConnectAfterSubscriptionRefresh = false
        connectJob?.cancel()
        connectJob = null
        disconnectJob?.cancel()
        tunnelSyncWatchJob?.cancel()
        tunnelSyncWatchJob = null
        backendSyncJob?.cancel()
        backendSyncJob = null
        backendSyncCompleted = false
        VpnSessionState.resetBackendSync()
        lastTunnelAttachAtMs = 0L
        pendingHashFailures.clear()
        hashFailureFlushJob?.cancel()
        hashFailureFlushJob = null
        bootstrapVpnMode = false
        markLocalDeviceOffline()
        repo.invalidatePublicReachabilityCache()
        _vpnState.value = VpnState.DISCONNECTING
        disconnectJob = viewModelScope.launch {
            try {
                stopVpnLocally(context)
                checkForAppUpdate()
            } finally {
                _vpnState.value = VpnState.DISCONNECTED
                SessionTrace.exit("MainViewModel.disconnect")
            }
        }
    }

    private suspend fun checkPromoApi(code: String): String {
        val res = repo.getApi().checkPromo(PromoCheckRequest(code, "monthly"))
        if (res.isSuccessful) return "Скидка ${res.body()!!.discount_percent}%!"
        return parseError(res.errorBody()?.string() ?: "") ?: "Не найден"
    }

    fun checkPromo(code: String, onResult: (String) -> Unit) {
        viewModelScope.launch {
            if (!repo.isMainVpnTunnelUp() && repo.isOnMobileData()) {
                val ok = runEphemeralApiBootstrap(appContext, force = true) {
                    runCatching { checkPromoApi(code) }
                        .fold(
                            onSuccess = { msg -> onResult(msg); true },
                            onFailure = { e ->
                                onResult(repo.humanizeHashFetchError(e.message))
                                false
                            },
                        )
                }
                if (!ok) {
                    onResult("Не удалось проверить промокод. Повторите.")
                }
                return@launch
            }
            runCatching {
                repo.withUserBackendApi { checkPromoApi(code) }
            }.onSuccess { onResult(it) }.onFailure { e ->
                onResult(repo.humanizeHashFetchError(e.message))
            }
        }
    }

    fun renameDevice(deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withBackendApi {
                    repo.getApi().renameDevice(deviceId, com.silent.vpn.data.DeviceRenameRequest(name))
                }
                if (res.isSuccessful) {
                    loadProfile()
                    onResult(true, null)
                } else {
                    onResult(false, parseError(res.errorBody()?.string() ?: "") ?: "Ошибка переименования")
                }
            }.onFailure {
                onResult(false, it.message ?: "Ошибка")
            }
        }
    }

    fun deleteDevice(deviceId: String, onResult: (Boolean, String?) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withBackendApi { repo.getApi().deleteDevice(deviceId) }
                if (res.isSuccessful) {
                    val isCurrentSession = deviceId == repo.getSessionDeviceId()
                    if (isCurrentSession) {
                        onResult(true, "__logout__")
                    } else {
                        loadProfile()
                        onResult(true, null)
                    }
                } else {
                    onResult(false, parseError(res.errorBody()?.string() ?: "") ?: "Ошибка удаления")
                }
            }.onFailure {
                onResult(false, it.message ?: "Ошибка")
            }
        }
    }

    private suspend fun initPaymentApi(planType: String): String {
        val res = repo.getApi().initPayment(com.silent.vpn.data.PaymentInitRequest(planType))
        if (res.isSuccessful) return res.body()!!.url
        throw IllegalStateException(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка оплаты")
    }

    fun initPayment(planType: String, onUrl: (String) -> Unit, onError: (String) -> Unit) {
        viewModelScope.launch {
            if (!repo.isMainVpnTunnelUp() && repo.isOnMobileData()) {
                val ok = runEphemeralApiBootstrap(appContext, force = true) {
                    runCatching { initPaymentApi(planType) }
                        .fold(
                            onSuccess = { url -> onUrl(url); true },
                            onFailure = { e ->
                                onError(e.message ?: "Ошибка оплаты")
                                false
                            },
                        )
                }
                if (!ok) onError("Не удалось открыть оплату. Повторите.")
                return@launch
            }
            runCatching {
                repo.withUserBackendApi { initPaymentApi(planType) }
            }.onSuccess { onUrl(it) }.onFailure { e ->
                onError(e.message ?: "Ошибка")
            }
        }
    }

    private fun hasVpnAccess(): Boolean = hasVpnAccessForProfile(_profile.value)

    private fun hasVpnAccessForProfile(p: UserProfile?): Boolean {
        if (p == null) return true
        if (p.is_admin) return true
        return p.subscription.is_active
    }

    /** Обновить UI; при истёкшей подписке на сервере — отключить main VPN. */
    private fun applyServerProfile(profile: UserProfile) {
        _profile.value = profile
        if (silentBootstrapSync || bootstrapVpnMode || WdttTunnelManager.isBootstrapMode()) return
        val hasAccess = hasVpnAccessForProfile(profile)
        val vpnActive = _vpnState.value == VpnState.CONNECTED ||
            _vpnState.value == VpnState.CONNECTING ||
            (SilentVpnService.isRunning && repo.isMainVpnTunnelUp())
        if (pendingConnectAfterSubscriptionRefresh && hasAccess && !vpnActive && _vpnState.value == VpnState.DISCONNECTED) {
            pendingConnectAfterSubscriptionRefresh = false
            _vpnError.value = null
            DebugLog.i("MainViewModel", "subscription restored — auto reconnect")
            connect(appContext)
            return
        }
        if (vpnActive && !hasAccess) {
            DebugLog.i("MainViewModel", "subscription expired on server — disconnect VPN")
            _vpnError.value = subscriptionRequiredMessage()
            viewModelScope.launch { disconnect(appContext) }
        }
    }

    private fun subscriptionRequiredMessage() =
        "Пробный период закончился. Оформите подписку в меню → Подписка."

    /** Только для bootstrap-VPN на экране входа: хеш + device_id boot:… */
    private fun bootstrapLaunchConfig(config: VpnConfig): VpnConfig {
        val withHash = applyBootstrapHash(config)
        if (withHash.device_id.startsWith("boot:")) return withHash
        val fp = repo.getOrCreatePreLoginFingerprint()
        return withHash.copy(device_id = "boot:$fp")
    }

    private fun applyBootstrapHash(config: VpnConfig): VpnConfig {
        val hashes = config.vk_hashes.filter { it.isNotBlank() }
        if (hashes.isNotEmpty()) return config
        val boot = repo.getBootstrapHash() ?: return config
        return config.copy(vk_hashes = listOf(boot))
    }

    private fun parseError(body: String): String? {
        if (body.isBlank()) return null
        return Regex(""""detail"\s*:\s*"([^"]+)"""").find(body)?.groupValues?.get(1)
            ?: body.take(120)
    }
}
