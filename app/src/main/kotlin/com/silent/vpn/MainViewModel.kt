package com.silent.vpn

import android.content.Context
import android.content.Intent
import android.os.SystemClock
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
import com.silent.vpn.data.DeviceInfo
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
import com.silent.vpn.data.ReferralInfo
import com.silent.vpn.data.RegisterRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.data.VpnHashesResponse
import com.silent.vpn.policy.OlcrtcSessionPolicy
import com.silent.vpn.security.AppIntegrity
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
import com.silent.vpn.vpn.TelegramPathWarmup
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.HashFailureReporter
import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.sync.MobileSyncLog
import com.silent.vpn.sync.TunnelSyncResult
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
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import javax.inject.Inject
import retrofit2.Response

private const val EPHEMERAL_TUNNEL_WAIT_ITER = 120
/** Пока открыт экран «Устройства/Сессии» и VPN ВЫКЛЮЧЕН — обновляем список по public API. */
private const val SESSIONS_POLL_MS = 10 * 1000L

enum class AppScreen { LOGIN, MAIN }

/** Единый флоу оплаты для всех клиентов: init → браузер → poll /payments/status/{label}. */
enum class PaymentUiState { IDLE, WAITING, COMPLETED, FAILED, TIMEOUT }

@HiltViewModel
class MainViewModel @Inject constructor(
    private val repo: SilentRepository,
    @ApplicationContext private val appContext: Context,
) : ViewModel() {

    private val _screen = MutableStateFlow(if (repo.isLoggedIn()) AppScreen.MAIN else AppScreen.LOGIN)
    val screen: StateFlow<AppScreen> = _screen

    private val _profile = MutableStateFlow<UserProfile?>(null)
    val profile: StateFlow<UserProfile?> = _profile

    private val _paymentState = MutableStateFlow(PaymentUiState.IDLE)
    val paymentState: StateFlow<PaymentUiState> = _paymentState
    private var paymentPollJob: Job? = null

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

    private val _pendingReferralCode = MutableStateFlow("")
    val pendingReferralCode: StateFlow<String> = _pendingReferralCode

    private val _bootstrapHash = MutableStateFlow(repo.getBootstrapHash())
    val bootstrapHash: StateFlow<String?> = _bootstrapHash

    private val _hashReady = MutableStateFlow(isHashReady())
    val hashReady: StateFlow<Boolean> = _hashReady

    private val _statusMsg = MutableStateFlow("")
    val statusMsg: StateFlow<String> = _statusMsg

    private val _bootstrapConnecting = MutableStateFlow(false)
    val bootstrapConnecting: StateFlow<Boolean> = _bootstrapConnecting

    /** Секунд до конца bootstrap-сессии; null — таймер не идёт. */
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
    /** Дедлайн bootstrap — один на сессию, не сбрасывается при переходе шаг 2 → шаг 1. */
    private var bootstrapDeadlineMs = 0L
    private var silentBootstrapSync = false
    /** Serialize Apply + connect ensure — иначе второй вызов видит silentBootstrapSync и сразу false. */
    private val olcrtcConfigEnsureMutex = Mutex()
    private var profilePollJob: Job? = null
    private var vpnProfilePollJob: Job? = null
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

        override fun isWifiSubscriptionPollAllowed(): Boolean =
            repo.isLoggedIn() &&
                !bootstrapVpnMode &&
                _screen.value == AppScreen.MAIN &&
                !repo.isOnMobileData()

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
        // olcrtc-config не тянем здесь — только login + sync при VK.
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
                        // Не clearTokens — пользователь остаётся авторизованным.
                    }
            }
            _screen.value = AppScreen.MAIN
            restoreCachedProfileToUi()
            restoreCachedThemeToUi()
            syncVpnStateFromSystem()
            DebugLog.i(
                "MainViewModel",
                "session restore bypass=${repo.getBypassFamily()} olcrtc=${repo.isOlcrtcBypass()} provider=${repo.getOlcrtcProvider()}",
            )
            viewModelScope.launch {
                runCatching { refreshSession() }
                    .onFailure { e ->
                        DebugLog.w("MainViewModel", "refreshSession: ${e.message}")
                    }
            }
            repo.mergeSavedHashesIntoCachedConfig()
            startConfigSync()
            // После переустановки APK olcrtc-кеш пуст; раньше прогрев был только на login.
            // Тот же ephemeral/public путь — без «выйти и зайти».
            if (repo.isOlcrtcBypass()) {
                viewModelScope.launch {
                    val need = listOf("telemost", "wbstream").filter {
                        repo.getCachedOlcrtcConfigForProvider(it) == null
                    }
                    if (need.isEmpty()) return@launch
                    com.silent.vpn.util.OlcrtcDiag.i(
                        com.silent.vpn.util.OlcrtcDiag.CFG,
                        "cold-start warm olcrtc slots=$need (no re-login)",
                    )
                    runCatching { ensureOlcrtcConfigApi(appContext, *need.toTypedArray()) }
                        .onFailure { e ->
                            DebugLog.w("MainViewModel", "cold-start olcrtc warm: ${e.message}")
                        }
                }
            }
        } else {
            repo.getCachedTheme()?.let { _theme.value = it }
            viewModelScope.launch { loadTheme() }
            viewModelScope.launch {
                if (SilentVpnService.isRunning && isHashReady()) {
                    reconcileLoginBootstrapSession(appContext)
                }
            }
        }
        com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener = configSyncListener
        com.silent.vpn.sync.VpnDataSyncBridge.onCycleCompleted = {
            applyCachedProfileAfterSync()
        }
        com.silent.vpn.sync.VpnDataSyncBridge.onOtaCheckInOverlaySession = {
            checkForAppUpdate(inOverlaySession = true)
        }
        viewModelScope.launch {
            delay(2_000)
            // На LTE OTA уже в overlay initial sync; не дублируем лишний overlay.
            if (!repo.isOnMobileData() || !SilentVpnService.isRunning) {
                checkForAppUpdate()
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.lastError.collect { err ->
                if (!err.isNullOrBlank() &&
                    !isIgnoredVpnError(err) &&
                    (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.CONNECTED)
                ) {
                    DebugLog.e("MainViewModel", "WDTT error: $err")
                    if (bootstrapVpnMode) {
                        _statusMsg.value = err
                        if (isBootstrapFatalError(err)) {
                            _vpnState.value = VpnState.DISCONNECTED
                            bootstrapVpnMode = false
                            cancelBootstrapSessionTimeout()
                            bootstrapContext?.let { stopVpnLocally(it) }
                        }
                    } else {
                        _vpnError.value = err
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
                        val workersOk = !bootstrapRequiresActiveWorkers() ||
                            WdttTunnelManager.activeWorkers.value >= 1
                        if (workersOk) {
                            _vpnState.value = VpnState.CONNECTED
                            onVpnTunnelReady()
                            val ctx = bootstrapContext
                            if (ctx != null) {
                                startBootstrapSessionTimeout(
                                    ctx,
                                    forceNewDeadline = bootstrapDeadlineMs <= System.currentTimeMillis(),
                                )
                            }
                        }
                        updateBootstrapReadyFlag()
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
                        markLocalDeviceOnline()
                        onVpnTunnelReady()
                        updateBootstrapReadyFlag()
                        if (!WdttTunnelManager.isBootstrapMode()) {
                            TelegramPathWarmup.schedule(viewModelScope)
                        }
                    }
                } else if (
                    _vpnState.value == VpnState.CONNECTED &&
                    !WdttTunnelManager.running.value &&
                    WdttTunnelManager.activeWorkers.value < 1
                ) {
                    TelegramPathWarmup.cancel()
                    _vpnState.value = VpnState.DISCONNECTED
                    backendSyncCompleted = false
                    repo.clearTunnelApiBase()
                    markLocalDeviceOffline()
                }
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.activeWorkers.collect {
                if (
                    bootstrapRequiresActiveWorkers() &&
                    bootstrapVpnMode &&
                    WdttTunnelManager.isBootstrapMode()
                ) {
                    if (
                        it >= 1 &&
                        WdttTunnelManager.tunnelReady.value &&
                        _vpnState.value == VpnState.CONNECTING
                    ) {
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady()
                        bootstrapContext?.let { ctx ->
                            startBootstrapSessionTimeout(
                                ctx,
                                forceNewDeadline = bootstrapDeadlineMs <= System.currentTimeMillis(),
                            )
                        }
                    }
                    updateBootstrapReadyFlag()
                }
            }
        }
        viewModelScope.launch {
            OlcrtcTunnelManager.tunnelReady.collect { ready ->
                if (!repo.isOlcrtcBypass()) return@collect
                if (ready) {
                    if (_vpnState.value == VpnState.DISCONNECTING) return@collect
                    DebugLog.i("MainViewModel", "olcrtc tunnel ready")
                    _vpnState.value = VpnState.CONNECTED
                    markLocalDeviceOnline()
                    onVpnTunnelReady()
                    // olcrtc: API на публичном nip.io, не 10.66.66.1
                    repo.clearTunnelApiBase()
                    startOlcrtcHeartbeatLoop()
                    return@collect
                }
                // Peer closed / network recover: сервис ещё жив → CONNECTING, иначе DISCONNECTED.
                when (_vpnState.value) {
                    VpnState.CONNECTED -> {
                        if (SilentVpnService.isRunning) {
                            DebugLog.w("MainViewModel", "olcrtc ready=false — reconnecting")
                            _vpnState.value = VpnState.CONNECTING
                            WdttTunnelManager.logUi(
                                "olcrtc_ui",
                                "туннель оборван — переподключение…",
                                2,
                            )
                        } else {
                            leaveOlcrtcSessionAndStopHeartbeat()
                            _vpnState.value = VpnState.DISCONNECTED
                        }
                    }
                    else -> Unit
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
                val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(bootHash, repo.getApiDeviceType(), fp))
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
                    DeviceRegisterRequest(repo.getDeviceDisplayName(), repo.getApiDeviceType(), fp, null, repo.getBootstrapHash()),
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
        // olcrtc: оба слота (Telemost+WB) пока bootstrap-туннель жив — как 1.0.160 dual-cache.
        runCatching {
            repo.ensureBootstrapTunnelApi()
            val (tm, wb) = repo.prefetchOlcrtcBothProviders()
            DebugLog.i(
                "MainViewModel",
                "login olcrtc-config both tm=$tm wb=$wb selected=${repo.getOlcrtcProvider()}",
            )
        }.onFailure { e ->
            DebugLog.w("MainViewModel", "login olcrtc-config: ${e.message}")
        }
        // ВАЖНО: тянем профиль напрямую по tunnel-base, пока активен API-overlay.
        // fetchProfileNow() здесь нельзя — он сразу выходит при isApiOverlayActive()==true,
        // поэтому профиль не грузился, и пользователь видел «Включите главный тумблер».
        return tryFetchProfileOnBase(tunnel) || _profile.value != null
    }

    /** Главный экран только после входа; bootstrap/pre-login остаётся на LOGIN. */
    private fun isMainVpnSessionForUi(): Boolean {
        if (!repo.isLoggedIn() || bootstrapVpnMode) return false
        // Залипший WDTT bootstrap-флаг после входа не должен кидать на LOGIN при olcrtc.
        if (WdttTunnelManager.isBootstrapMode() && !repo.isOlcrtcBypass()) return false
        if (WdttTunnelManager.isBootstrapMode() && repo.isOlcrtcBypass()) {
            WdttTunnelManager.clearStaleSession()
        }
        return true
    }

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

    /** На LTE до initial sync не показываем устаревшую подписку из кеша. */
    private fun shouldDeferProfileUntilSync(): Boolean =
        repo.isOnMobileData() &&
            SilentRepository.APP_EXCLUDED_FROM_VPN &&
            !VpnSessionState.tunnelDataSyncCompleted &&
            (VpnSessionState.initialOverlaySyncActive ||
                _vpnState.value == VpnState.CONNECTING ||
                (_vpnState.value == VpnState.CONNECTED && SilentVpnService.isRunning))

    private fun restoreCachedProfileToUi() {
        if (shouldDeferProfileUntilSync()) return
        repo.getCachedProfile()?.let { cached ->
            if (_profile.value == null) _profile.value = cached
        }
    }

    private fun applyCachedProfileAfterSync() {
        repo.getCachedProfile()?.let { applyServerProfile(it, force = true) }
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
            if (repo.isLoggedIn() && !VpnSessionState.isBusy()) {
                val refreshOnResume = !repo.isOnMobileData() || _profile.value == null
                if (refreshOnResume) {
                    runCatching {
                        if (bootstrapVpnMode && SilentVpnService.isRunning) {
                            withBootstrapBackendApi { fetchProfileNow(force = true) }
                            if (_profile.value != null) {
                                disconnectBootstrapVpn(appContext)
                            }
                        } else if (!repo.isOnMobileData()) {
                            refreshWifiSubscriptionProfile()
                        } else {
                            fetchProfileNow(force = true)
                        }
                    }.onFailure { e ->
                        DebugLog.w("MainViewModel", "resume profile fetch: ${e.message}")
                    }
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
        // /users/me может жить по IP, а olcrtc2-config — нет. Для apiBlock (assign) ephemeral обязателен.
        if (
            apiBlock == null &&
            !repo.isOnMobileData() &&
            repo.isPublicBackendReachable(forceProbe = true)
        ) {
            return false
        }

        val boot = HashParser.extract(repo.getBootstrapHash().orEmpty()) ?: return false
        val fp = runCatching { repo.getDeviceFingerprint() }.getOrNull() ?: return false

        silentBootstrapSync = true
        try {
            repo.clearTunnelApiBase()
            var config = runCatching {
                val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(boot, repo.getApiDeviceType(), fp))
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
                if (
                    bootstrapRequiresActiveWorkers() &&
                    WdttTunnelManager.activeWorkers.value < 1 &&
                    attempt < 24
                ) {
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

    /**
     * Public API (queen :443) часто недоступен с LTE и с «битого» Wi‑Fi → olcrtc-config пустой.
     * Ephemeral VK bootstrap → fetch ТОЛЬКО через 10.66.66.1 → stop (кеш v14 остаётся).
     * Mutex: Apply и connect не отменяют друг друга через silentBootstrapSync.
     */
    suspend fun ensureOlcrtcConfigApi(context: Context, vararg providers: String): Boolean =
        olcrtcConfigEnsureMutex.withLock {
            val want = providers
                .map { com.silent.vpn.policy.OlcrtcSessionPolicy.normalizeProvider(it) }
                .ifEmpty { listOf(repo.getOlcrtcProvider()) }
                .distinct()
            fun allCached(): Boolean = want.all { repo.getCachedOlcrtcConfigForProvider(it) != null }
            if (allCached()) {
                com.silent.vpn.util.OlcrtcDiag.i(
                    com.silent.vpn.util.OlcrtcDiag.CFG,
                    "ensureApi skip — all cached providers=$want",
                )
                return@withLock true
            }
            val bootUp = WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value
            val mainUp = repo.isMainVpnTunnelUp()
            if (bootUp || mainUp) {
                var any = false
                for (p in want) {
                    val cfg = runCatching { repo.fetchOlcrtcConfigTunnelOnly(p) }.getOrNull()
                    if (cfg?.providers?.get(p)?.room?.isNotBlank() == true) any = true
                }
                com.silent.vpn.util.OlcrtcDiag.i(
                    com.silent.vpn.util.OlcrtcDiag.CFG,
                    "ensureApi via live tunnel boot=$bootUp main=$mainUp any=$any cached=${allCached()}",
                )
                return@withLock any || allCached()
            }
            // Wi‑Fi: public assign может быть 20–60с (create room). Короче 45с → false miss.
            if (!repo.isOnMobileData()) {
                var any = false
                for (p in want) {
                    if (
                        runCatching {
                            repo.fetchOlcrtcConfig(
                                p,
                                publicConnectSec = 20L,
                                publicReadSec = 75L,
                            )
                        }.getOrNull()?.providers?.get(p)?.room?.isNotBlank() == true
                    ) {
                        any = true
                    }
                }
                if (any || allCached()) {
                    com.silent.vpn.util.OlcrtcDiag.i(
                        com.silent.vpn.util.OlcrtcDiag.CFG,
                        "ensureApi direct public ok any=$any cached=${allCached()}",
                    )
                    return@withLock true
                }
                com.silent.vpn.util.OlcrtcDiag.w(
                    com.silent.vpn.util.OlcrtcDiag.CFG,
                    "WiFi public miss → ephemeral for olcrtc-config providers=$want",
                )
            } else {
                com.silent.vpn.util.OlcrtcDiag.w(
                    com.silent.vpn.util.OlcrtcDiag.CFG,
                    "LTE: ephemeral bootstrap for olcrtc-config providers=$want",
                )
            }
            val ok = runEphemeralApiBootstrap(context, force = true) {
                repo.ensureBootstrapTunnelApi()
                var got = false
                for (p in want) {
                    val cfg = repo.fetchOlcrtcConfigTunnelOnly(p)
                    com.silent.vpn.util.OlcrtcDiag.i(
                        com.silent.vpn.util.OlcrtcDiag.CFG,
                        "ephemeral tunnel-only $p room=${cfg?.providers?.get(p)?.room?.take(28)}",
                    )
                    if (cfg?.providers?.get(p)?.room?.isNotBlank() == true) got = true
                }
                got
            }
            com.silent.vpn.util.OlcrtcDiag.i(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "ephemeral olcrtc-config ok=$ok mobile=${repo.isOnMobileData()} " +
                    "tm=${repo.getCachedOlcrtcConfigForProvider("telemost") != null} " +
                    "wb=${repo.getCachedOlcrtcConfigForProvider("wbstream") != null}",
            )
            ok || allCached()
        }

    /** Apply: остановить connect, иначе CancellationException рвёт ephemeral mid-flight. */
    fun cancelPendingOlcrtcConnectForApply() {
        connectJob?.cancel(CancellationException("olcrtc-apply"))
        connectJob = null
        if (_vpnState.value == VpnState.CONNECTING) {
            _vpnState.value = VpnState.DISCONNECTED
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
                        DeviceRegisterRequest(repo.getDeviceDisplayName(), repo.getApiDeviceType(), fp, null, null),
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
                repo.getApi().requestHashRefresh(ConnectRequest(fp, repo.getApiDeviceType()))
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
    private var olcrtcHeartbeatJob: Job? = null
    /** Провайдер/room сессии на момент connect — leave не читает prefs после Apply. */
    @Volatile private var olcrtcSessionProvider: String? = null
    @Volatile private var olcrtcSessionRoomDbId: String? = null
    private var logoutJob: Job? = null
    @Volatile private var logoutGeneration = 0
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
            markLocalDeviceOnline()
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
        if (!shouldDeferProfileUntilSync()) {
            restoreCachedProfileToUi()
        }
        markLocalDeviceOnline()
        if (!bootstrapVpnMode && repo.isLoggedIn()) {
            watchTunnelDataSyncFromCache()
        }
    }

    /**
     * После tunnelReady — ждём [VpnDataSyncService] (один initial sync), обновляем UI из кеша.
     * На LTE — variant 1: повторный fetch профиля (как перед connect).
     */
    private fun watchTunnelDataSyncFromCache() {
        tunnelSyncWatchJob?.cancel()
        tunnelSyncWatchJob = viewModelScope.launch {
            val cachedSubBefore = _profile.value?.subscription?.is_active
            MobileSyncLog.i(
                "watch",
                "start cachedSubActive=$cachedSubBefore mobile=${repo.isOnMobileData()}",
            )
            restoreCachedThemeToUi()
            refreshHashState()
            if (_vpnState.value == VpnState.CONNECTED) {
                markLocalDeviceOnline()
            }

            if (!VpnSessionState.tunnelDataSyncCompleted) {
                val deadline = System.currentTimeMillis() + 120_000L
                while (
                    System.currentTimeMillis() < deadline &&
                    !VpnSessionState.tunnelDataSyncCompleted &&
                    _vpnState.value != VpnState.DISCONNECTING &&
                    WdttTunnelManager.tunnelReady.value &&
                    SilentVpnService.isRunning
                ) {
                    delay(500)
                }
                backendSyncCompleted = VpnSessionState.tunnelDataSyncCompleted
            } else {
                backendSyncCompleted = true
            }

            MobileSyncLog.i(
                "watch",
                "sync wait done completed=${VpnSessionState.tunnelDataSyncCompleted} mobile=${repo.isOnMobileData()}",
            )

            restoreCachedThemeToUi(refreshFromSync = true)
            refreshHashState()
            flushPendingHashFailures()
            if (VpnSessionState.tunnelDataSyncCompleted) {
                applyCachedProfileAfterSync()
            }
            if (_vpnState.value == VpnState.CONNECTED && SilentVpnService.isRunning) {
                markLocalDeviceOnline()
            }
            // Как в 1.0.160: на VK-сессии olcrtc-слоты не трогаем. `/olcrtc2-config` — это
            // assign комнат на сервере, а не чтение; на каждом connect это лишний трафик
            // в туннеле и занятые комнаты у пользователя, который olcrtc не включал.
            // Слоты дотягиваются в Apply «Вариантов обхода» и перед olcrtc-connect.
        }
    }

    private var updateCheckInFlight = false
    private var otaCheckedThisVpnSession = false

    /** OTA: Wi‑Fi — public HTTPS; LTE — overlay только до initial sync, потом direct tunnel. */
    fun checkForAppUpdate(inOverlaySession: Boolean = false) {
        if (updateCheckInFlight) return
        if (!inOverlaySession && otaCheckedThisVpnSession) return
        updateCheckInFlight = true
        viewModelScope.launch {
            try {
                val version = com.silent.vpn.BuildConfig.VERSION_NAME
                val vpnUp = SilentVpnService.isRunning &&
                    WdttTunnelManager.tunnelReady.value &&
                    !WdttTunnelManager.isBootstrapMode()

                var ok = false
                if (vpnUp && repo.allowsBackgroundConfigSync()) {
                    ok = runCatching {
                        if (inOverlaySession || repo.canUseMobileDirectTunnelApi()) {
                            repo.prepareMainVpnDirectApi()
                            applyCheckUpdateResponse(version)
                        } else {
                            repo.withOtaBackendApi { applyCheckUpdateResponse(version) }
                        }
                    }.getOrDefault(false)
                }

                if (!ok && !repo.isOnMobileData()) {
                    val bases = listOf(
                        repo.getPublicServerUrl().trimEnd('/'),
                        "https://${SilentRepository.DEFAULT_SERVER_HOST}",
                    ).distinct()
                    for (base in bases) {
                        if (runCatching { tryCheckUpdateOnBase(base, version) }.getOrDefault(false)) {
                            ok = true
                            break
                        }
                    }
                }

                if (!ok) {
                    DebugLog.w(
                        "MainViewModel",
                        "checkUpdate failed vpnUp=$vpnUp mobile=${repo.isOnMobileData()} excluded=${SilentRepository.APP_EXCLUDED_FROM_VPN}",
                    )
                }
            } catch (e: Exception) {
                DebugLog.w("MainViewModel", "checkUpdate: ${e.message}")
            } finally {
                updateCheckInFlight = false
                otaCheckedThisVpnSession = true
            }
        }
    }

    private suspend fun applyCheckUpdateResponse(version: String): Boolean {
        val res = repo.getApi().checkUpdate(repo.getOtaPlatform(), version)
        if (!res.isSuccessful) {
            DebugLog.w("MainViewModel", "checkUpdate HTTP ${res.code()} via ${repo.getServerUrl()}")
            return false
        }
        val body = res.body()
        if (body?.available == true) {
            _updateInfo.value = body
            updateApiBaseUrl = if (repo.isOnMobileData()) {
                repo.getServerUrl().trimEnd('/')
            } else {
                repo.getPublicServerUrl().trimEnd('/')
            }
            DebugLog.i("MainViewModel", "checkUpdate: available ${body.version}")
        } else {
            _updateInfo.value = null
            DebugLog.i("MainViewModel", "checkUpdate: up to date v=$version")
        }
        return true
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

    /** Профиль приходит из initial sync + ConfigSync — без периодического overlay/poll. */
    fun setVpnProfilePolling(active: Boolean) {
        vpnProfilePollJob?.cancel()
        vpnProfilePollJob = null
    }

    /** Главный экран: одна проверка OTA при открытии (только без VPN). */
    fun setUpdatePolling(active: Boolean) {
        if (active && !otaCheckedThisVpnSession) checkForAppUpdate()
    }

    private suspend fun tryCheckUpdateOnBase(base: String, version: String): Boolean {
        repo.useApiBase(base)
        val res = repo.getApi().checkUpdate(repo.getOtaPlatform(), version)
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
        val primaryUrl = repo.resolveUpdateDownloadUrl(info) ?: return
        val fallbackGh = info.github_download_url?.trim()?.takeIf { it.startsWith("http") }
        viewModelScope.launch {
            _updateDownloading.value = true
            _updateProgress.value = 0
            try {
                val useCdn = repo.isPublicCdnUpdateUrl(primaryUrl)
                DebugLog.i(
                    "MainViewModel",
                    "update download url=$primaryUrl cdn=$useCdn lteTunnel=${repo.shouldUseTunnelUpdateDownload()}",
                )
                val downloadFrom: suspend (String) -> java.io.File = { url ->
                    AppUpdateManager.downloadApk(
                        context,
                        url,
                        info.filename ?: "update.apk",
                        repo.buildDownloadClient(),
                        expectedSize = info.size.coerceAtLeast(0L),
                    ) { pct -> _updateProgress.value = pct }
                }
                val file = repo.withUpdateDownloadRoute {
                    runCatching { downloadFrom(primaryUrl) }.getOrElse { first ->
                        if (repo.shouldUseTunnelUpdateDownload()) throw first
                        val alt = fallbackGh?.takeIf { it != primaryUrl }
                            ?: info.download_url?.trim()?.takeIf { it.startsWith("http") && it != primaryUrl }
                        if (alt == null) throw first
                        DebugLog.w("MainViewModel", "update retry from GitHub: $alt")
                        downloadFrom(alt)
                    }
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

    /** TV/arm32: ждём libclient-воркеров; телефон — достаточно tunnelReady (как раньше). */
    private fun bootstrapRequiresActiveWorkers(): Boolean =
        com.silent.vpn.util.DevicePlatform.isTv(appContext)

    private fun updateBootstrapReadyFlag() {
        val workersOk = !bootstrapRequiresActiveWorkers() ||
            WdttTunnelManager.activeWorkers.value >= 1
        _bootstrapReady.value = !repo.isLoggedIn() &&
            bootstrapVpnMode &&
            SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            workersOk &&
            _vpnState.value == VpnState.CONNECTED
    }

    private suspend fun fetchProfileNow(force: Boolean = false): Boolean {
        if (
            !force &&
            (_vpnState.value == VpnState.CONNECTING ||
                _vpnState.value == VpnState.DISCONNECTING ||
                WdttTunnelManager.isApiOverlayActive())
        ) {
            return _profile.value != null
        }
        if (
            force &&
            repo.isOnMobileData() &&
            (_vpnState.value == VpnState.CONNECTING ||
                _vpnState.value == VpnState.DISCONNECTING ||
                WdttTunnelManager.isApiOverlayActive())
        ) {
            return _profile.value != null
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
                DebugLog.w("MainViewModel", "profile 401 — refresh without logout")
                return repo.fetchProfileLive().fold(
                    onSuccess = { p ->
                        applyServerProfile(p)
                        true
                    },
                    onFailure = { e ->
                        DebugLog.w("MainViewModel", "profile after refresh failed: ${e.message} — keep login")
                        false
                    },
                )
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
                DebugLog.w("MainViewModel", "profile 401 on $base — refresh without logout")
                return repo.fetchProfileLive().fold(
                    onSuccess = { p ->
                        applyServerProfile(p)
                        true
                    },
                    onFailure = { e ->
                        DebugLog.w("MainViewModel", "profile refresh on $base failed: ${e.message} — keep login")
                        false
                    },
                )
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
        invalidatePendingLogout()
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
                    device_type = repo.getApiDeviceType(),
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

    fun register(email: String, password: String, rememberMe: Boolean, referralOrPromo: String = "") {
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
                    val res = registerAttempt(email, password, referralOrPromo)
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

    private suspend fun registerAttempt(
        email: String,
        password: String,
        referralOrPromo: String = "",
    ): retrofit2.Response<Map<String, String>> {
        awaitTunnelApiReady()
        val bases = preLoginApiBases()
        if (bases.isEmpty()) {
            throw Exception("VPN ещё не готов. Дождитесь «Канал готов» на шаге 1.")
        }
        var lastError: Exception? = null
        val code = referralOrPromo.trim().ifBlank { null }
        for (base in bases) {
            try {
                repo.useApiBase(base)
                val res = repo.getApi().register(RegisterRequest(email, password, code))
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
        invalidatePendingLogout()
        _screen.value = AppScreen.MAIN
        startConfigSync()
        if (!skipProfileFetch && _profile.value == null) {
            loadProfile()
        }
    }

    override fun onCleared() {
        vpnProfilePollJob?.cancel()
        profilePollJob?.cancel()
        stopConfigSync()
        com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener = null
        com.silent.vpn.sync.VpnDataSyncBridge.onCycleCompleted = null
        com.silent.vpn.sync.VpnDataSyncBridge.onOtaCheckInOverlaySession = null
        super.onCleared()
    }

    private suspend fun disconnectBootstrapVpn(context: Context) {
        if (!bootstrapVpnMode) return
        cancelBootstrapSessionTimeout()
        bootstrapDeadlineMs = 0L
        WdttTunnelManager.prepareForShutdown()
        stopVpnLocally(context)
        WdttTunnelManager.stopAndAwait()
        WdttTunnelManager.clearStaleSession()
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
            bootstrapDeadlineMs = now + com.silent.vpn.util.DevicePlatform.bootstrapSessionMs(appContext)
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
        DebugLog.i("MainViewModel", "bootstrap session expired (${com.silent.vpn.util.DevicePlatform.bootstrapSessionMs(appContext) / 1000}s)")
        resetBootstrapDeadline()
        stopVpnLocally(ctx)
        bootstrapVpnMode = false
        bootstrapContext = null
        repo.clearTunnelApiBase()
        _vpnState.value = VpnState.DISCONNECTED
        val min = com.silent.vpn.util.DevicePlatform.bootstrapSessionMinutes(appContext)
        _statusMsg.value = "Время временного интернета истекло ($min мин). Закройте приложение и запустите снова."
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

    private fun friendlyBootstrapFailureMessage(): String? {
        WdttTunnelManager.lastError.value?.takeIf { it.isNotBlank() }?.let { return it }
        val stats = WdttTunnelManager.stats.value.trim()
        if (stats.isBlank() || stats.contains("Ожидание данных", ignoreCase = true)) {
            return if (com.silent.vpn.util.DevicePlatform.isTv(appContext)) {
                "VPN не поднялся на приставке. Проверьте интернет и перезапустите приложение."
            } else {
                null
            }
        }
        return stats.takeIf { !stats.contains("Ожидание данных", ignoreCase = true) }
    }

    /** Bootstrap VPN on login screen — reach backend through user's VK hash. */
    fun ensureBootstrapVpn(context: Context) {
        if (!AppIntegrity.ensureOkForVpn(context)) {
            _vpnError.value = AppIntegrity.failMessage()
            _statusMsg.value = AppIntegrity.failMessage()
            WdttTunnelManager.traceApp("integrity_fail", AppIntegrity.failMessage(), isError = true)
            return
        }
        if (_bootstrapExpired.value) {
            WdttTunnelManager.traceApp("bootstrap_skip", "bootstrap пропущен: сессия истекла")
            return
        }
        if (repo.isLoggedIn()) {
            WdttTunnelManager.traceApp("bootstrap_skip", "bootstrap пропущен: уже вошли")
            return
        }
        // Bootstrap всегда VK/WDTT — olcrtc только для основного VPN после входа.
        if (!isHashReady()) {
            WdttTunnelManager.traceApp("bootstrap_skip", "bootstrap пропущен: нет хеша в сборке", isError = true)
            return
        }
        if (bootstrapConnectingInternal) {
            WdttTunnelManager.traceApp("bootstrap_skip", "bootstrap уже подключается")
            return
        }
        if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            bootstrapContext = context.applicationContext
            resumeBootstrapTimerIfNeeded()
            refreshBootstrapCountdownNow()
            updateBootstrapReadyFlag()
            WdttTunnelManager.traceApp("bootstrap_resume", "bootstrap уже подключён, таймер возобновлён")
            return
        }
        ensureBootstrapVpnWdttContinue(context)
    }

    private fun ensureBootstrapVpnWdttContinue(context: Context) {
        val tv = com.silent.vpn.util.DevicePlatform.isTv(appContext)
        WdttTunnelManager.traceApp(
            "bootstrap_start",
            "старт bootstrap VPN (TV=$tv, ABI=${com.silent.vpn.util.DevicePlatform.primaryAbi()})",
        )
        DebugLog.i("MainViewModel", "ensureBootstrapVpn start")
        viewModelScope.launch {
            bootstrapConnectingInternal = true
            _bootstrapConnecting.value = true
            _vpnError.value = null
            try {
                val boot = HashParser.extract(repo.getBootstrapHash().orEmpty())
                    ?: run {
                        _statusMsg.value = "Неверный bootstrap-хеш в сборке приложения."
                        WdttTunnelManager.traceApp("bootstrap_hash", "неверный bootstrap-хеш", isError = true)
                        return@launch
                    }
                val fp = repo.getOrCreatePreLoginFingerprint()
                val config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))

                if (config.vk_hashes.isEmpty()) {
                    _statusMsg.value = "Нет VK-хеша для bootstrap"
                    WdttTunnelManager.traceApp("bootstrap_hash", "пустой vk_hashes в конфиге", isError = true)
                    return@launch
                }
                bootstrapVpnMode = true
                bootstrapContext = context.applicationContext
                _bootstrapExpired.value = false
                _vpnState.value = VpnState.CONNECTING
                repo.resetVkCredSessionEscalate()
                WdttTunnelManager.consumeFloodEscalate()

                val waitIterations = if (tv) 180 else 60
                var connectedOk = false

                for (attempt in 0 until 3) {
                    if (_vpnState.value != VpnState.CONNECTING && attempt > 0) break
                    _vpnState.value = VpnState.CONNECTING
                    val modeLabel = repo.vkCredStrategyLabel()
                    WdttTunnelManager.traceApp(
                        "bootstrap_connect",
                        "FGS CONNECT attempt=${attempt + 1} mode=$modeLabel device=${config.device_id.take(8)}… hashes=${config.vk_hashes.size}",
                    )
                    if (attempt > 0) {
                        _statusMsg.value = "Запасной режим: $modeLabel…"
                        stopVpnLocally(context)
                        repeat(20) {
                            if (!SilentVpnService.isRunning && !WdttTunnelManager.running.value) return@repeat
                            delay(200)
                        }
                    }
                    val intent = Intent(context, SilentVpnService::class.java).apply {
                        action = SilentVpnService.ACTION_CONNECT
                        putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(config))
                        putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, true)
                    }
                    ContextCompat.startForegroundService(context, intent)

                    var attemptOk = false
                    for (tick in 0 until waitIterations) {
                        delay(500)
                        if (_vpnState.value != VpnState.CONNECTING) return@launch
                        val workers = WdttTunnelManager.activeWorkers.value
                        val workersOk = !tv || workers >= 1
                        if (tick % 4 == 0 && tv) {
                            _statusMsg.value = when {
                                workers >= 1 -> "Подключение VPN… воркеры $workers"
                                WdttTunnelManager.tunnelReady.value -> "Подключение VPN… WireGuard готов, ждём канал"
                                else -> "Подключение VPN…"
                            }
                        }
                        if (
                            WdttTunnelManager.tunnelReady.value &&
                            WdttTunnelManager.running.value &&
                            workersOk
                        ) {
                            attemptOk = true
                            break
                        }
                        if (
                            tick >= 6 &&
                            !repo.isLegacyCaptchaStrategy() &&
                            workers < 1 &&
                            WdttTunnelManager.consumeFloodEscalate()
                        ) {
                            break
                        }
                    }
                    if (attemptOk) {
                        connectedOk = true
                        break
                    }

                    val flooded = WdttTunnelManager.consumeFloodEscalate()
                    if (!repo.escalateVkCredSession()) break
                    WdttTunnelManager.traceApp(
                        "bootstrap_escalate",
                        "timeout/flood escalate → ${repo.vkCredStrategyLabel()}${if (flooded) " (flood)" else ""}",
                        isError = true,
                    )
                }

                if (connectedOk) {
                    _vpnState.value = VpnState.CONNECTED
                    WdttTunnelManager.traceApp(
                        "bootstrap_ok",
                        "bootstrap OK: workers=${WdttTunnelManager.activeWorkers.value} tunnel=${WdttTunnelManager.tunnelReady.value}",
                    )
                    onVpnTunnelReady(config)
                    repo.ensureBootstrapTunnelApi()
                    startBootstrapSessionTimeout(context, forceNewDeadline = true)
                    return@launch
                }

                if (_vpnState.value == VpnState.CONNECTING) {
                    cancelBootstrapSessionTimeout()
                    stopVpnLocally(context)
                    bootstrapVpnMode = false
                    _vpnState.value = VpnState.DISCONNECTED
                    val failMsg = friendlyBootstrapFailureMessage()
                        ?: "Интернет через VPN не поднялся. Закройте приложение и запустите снова."
                    WdttTunnelManager.traceApp(
                        "bootstrap_timeout",
                        "таймаут: running=${WdttTunnelManager.running.value} " +
                            "tunnel=${WdttTunnelManager.tunnelReady.value} " +
                            "workers=${WdttTunnelManager.activeWorkers.value} " +
                            "stats=${WdttTunnelManager.stats.value}",
                        isError = true,
                    )
                    _statusMsg.value = failMsg
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                DebugLog.e("MainViewModel", "ensureBootstrapVpn failed", e)
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
            DeviceRegisterRequest(repo.getDeviceDisplayName(), repo.getApiDeviceType(), repo.getDeviceFingerprint(), null, boot)
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

    private fun invalidatePendingLogout() {
        logoutGeneration++
        logoutJob?.cancel()
        logoutJob = null
    }

    fun logout(context: Context? = null) {
        if (_screen.value == AppScreen.LOGIN) return
        val gen = ++logoutGeneration
        logoutJob?.cancel()
        logoutJob = viewModelScope.launch {
            try {
                val fp = if (repo.hasSessionFingerprint()) {
                    runCatching { repo.getDeviceFingerprint() }.getOrNull()
                } else null
                val accessToken = repo.getAccessToken()

                bootstrapVpnMode = false
                bootstrapContext = null
                cancelBootstrapSessionTimeout()
                resetBootstrapDeadline()

                if (_vpnState.value == VpnState.CONNECTED || _vpnState.value == VpnState.CONNECTING) {
                    if (repo.isOlcrtcBypass()) {
                        leaveOlcrtcSessionAndStopHeartbeat()
                    }
                    context?.let { stopVpnLocally(it) }
                }

                if (gen != logoutGeneration) return@launch

                if (fp != null && accessToken != null) {
                    runCatching {
                        val res = repo.getApi().logoutSession(DisconnectRequest(fp))
                        if (!res.isSuccessful) {
                            Log.w("MainViewModel", "logout API ${res.code()}")
                        }
                    }
                }

                if (gen != logoutGeneration) return@launch

                stopConfigSync()
                repo.clearCachedProfile()
                repo.clearSessionFingerprint()
                repo.clearSessionDeviceId()
                repo.clearCachedVpnConfig()
                repo.clearSavedHashItems()
                repo.clearSyncRevisions()
                repo.clearTunnelApiBase()
                repo.clearTokens()

                _sessionDeviceId.value = null
                _profile.value = null
                _vpnState.value = VpnState.DISCONNECTED
                _authError.value = null
                _vpnError.value = null
                _regDone.value = false
                _forgotSent.value = false
                _bootstrapExpired.value = false
                _statusMsg.value = ""
                bootstrapConnectingInternal = false
                _bootstrapConnecting.value = false
                restoreCachedThemeToUi()
                loadTheme()
                _screen.value = AppScreen.LOGIN

                if (gen != logoutGeneration) return@launch

                context?.let { ctx ->
                    repeat(24) {
                        if (!SilentVpnService.isRunning && !WdttTunnelManager.running.value) return@repeat
                        delay(250)
                    }
                    if (WdttTunnelManager.running.value) {
                        runCatching { WdttTunnelManager.stopAndAwait() }
                    }
                    VpnBackendSync.stop()
                    VpnSessionState.resetBackendSync()
                    if (gen == logoutGeneration) {
                        ensureBootstrapForAuthFlow(ctx)
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Log.w("MainViewModel", "logout: ${e.message}")
            }
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
        WdttTunnelManager.ensureApiOverlayOff()
        val leftoverNative = OlcrtcSessionPolicy.shouldHardResetLeftoverNative(
            vpnServiceRunning = SilentVpnService.isRunning,
            nativeRunning = OlcrtcTunnelManager.running.value,
            tunnelReady = OlcrtcTunnelManager.tunnelReady.value,
        )
        // Не hardReset только потому что выбран olcrtc: ephemeral/bootstrap stop
        // иначе убивает уже стартовавший Telemost и стирает комнату.
        if (leftoverNative && !SilentVpnService.isRunning) {
            OlcrtcTunnelManager.hardReset("disconnect_leftover")
        }
        if (SilentVpnService.isRunning) {
            runCatching {
                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_DISCONNECT
                }
                context.startService(intent)
            }
        } else {
            WdttTunnelManager.stop()
        }
    }

    fun connect(context: Context, olcrtcReassignAttempt: Int = 0) {
        SessionTrace.enter("MainViewModel.connect", "state=${_vpnState.value}")
        if (!AppIntegrity.ensureOkForVpn(context)) {
            _vpnError.value = AppIntegrity.failMessage()
            _vpnState.value = VpnState.DISCONNECTED
            SessionTrace.exit("MainViewModel.connect", "integrity_fail")
            return
        }
        if (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.DISCONNECTING) {
            val stuckOlcrtc =
                repo.isOlcrtcBypass() &&
                    !OlcrtcTunnelManager.tunnelReady.value &&
                    (
                        !OlcrtcTunnelManager.lastError.value.isNullOrBlank() ||
                            (
                                !OlcrtcTunnelManager.running.value &&
                                    !OlcrtcTunnelManager.isStarting() &&
                                    SilentVpnService.isRunning
                                )
                        )
            if (stuckOlcrtc) {
                DebugLog.w("MainViewModel", "connect: unstick olcrtc CONNECTING after fail")
                stopVpnLocally(context.applicationContext)
                _vpnState.value = VpnState.DISCONNECTED
            } else {
                DebugLog.i("MainViewModel", "connect ignored: operation in progress")
                SessionTrace.exit("MainViewModel.connect", "busy")
                return
            }
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
            otaCheckedThisVpnSession = false
            VpnSessionState.resetBackendSync()
            if (VpnNetworkHelper.isOtherVpnActive(context)) {
                DebugLog.i("MainViewModel", "Подключение заменит другой активный VPN")
            }
            try {
            // После входа WDTT bootstrap мог оставить isBootstrapMode=true → вылет на LOGIN.
            if (repo.isLoggedIn() && WdttTunnelManager.isBootstrapMode() && !WdttTunnelManager.running.value) {
                WdttTunnelManager.clearStaleSession()
            }
            bootstrapVpnMode = false
            runCatching {
                if (!shouldDeferProfileUntilSync()) {
                    restoreCachedProfileToUi()
                }
                if (!repo.isOnMobileData()) {
                    refreshWifiSubscriptionProfile()
                }
                val subCached = _profile.value?.subscription?.is_active
                MobileSyncLog.i(
                    "connect",
                    "pre-check subCached=$subCached mobile=${repo.isOnMobileData()} vpnUp=${VpnSessionState.isActive()}",
                )
                val cachedCfg = loadCachedVpnConfig()
                val lteStaleSubConnect = repo.isOnMobileData() &&
                    cachedCfg != null &&
                    isConfigConnectable(cachedCfg)
                if (!hasVpnAccess()) {
                    if (lteStaleSubConnect) {
                        MobileSyncLog.i(
                            "connect",
                            "LTE stale sub cache — connect first, verify in one overlay sync",
                        )
                    } else if (repo.isOnMobileData() && !VpnSessionState.isActive()) {
                        MobileSyncLog.i("connect", "no access on LTE — ephemeral bootstrap")
                        runEphemeralApiBootstrap(context, force = true)
                        restoreCachedProfileToUi()
                        MobileSyncLog.i(
                            "connect",
                            "after ephemeral subActive=${_profile.value?.subscription?.is_active}",
                        )
                    }
                    if (!hasVpnAccess() && !lteStaleSubConnect) {
                        pendingConnectAfterSubscriptionRefresh = true
                        _vpnState.value = VpnState.DISCONNECTED
                        _vpnError.value = null
                        _vpnError.value = subscriptionRequiredMessage()
                        return@launch
                    }
                }

                val fp = runCatching { repo.getDeviceFingerprint() }.getOrElse {
                    if (repo.hasSessionFingerprint()) throw it
                    repo.startNewSession()
                }

                // olcrtc: не брать WDTT из кеша — иначе всегда VK.
                if (repo.isOlcrtcBypass()) {
                    WdttTunnelManager.traceApp("olcrtc", "connect start provider=${repo.getOlcrtcProvider()}")
                    if (android.net.VpnService.prepare(context) != null) {
                        _vpnError.value = "Нужно разрешение VPN"
                        _vpnState.value = VpnState.DISCONNECTED
                        return@launch
                    }
                    val t0 = SystemClock.elapsedRealtime()
                    fun olcMs() = SystemClock.elapsedRealtime() - t0
                    // Кеш / сеть; при miss — ephemeral (Wi‑Fi без :443 и LTE одинаково).
                    var olc = repo.resolveOlcrtcConfigForConnect()
                    var provider = repo.getOlcrtcProvider()
                    var p = olc?.providers?.get(provider)
                    if (
                        (olc == null || p == null || p.room.isBlank()) &&
                        olcrtcReassignAttempt < 2
                    ) {
                        com.silent.vpn.util.OlcrtcDiag.w(
                            com.silent.vpn.util.OlcrtcDiag.CFG,
                            "connect miss → ensureOlcrtcConfigApi provider=$provider mobile=${repo.isOnMobileData()}",
                        )
                        ensureOlcrtcConfigApi(context, provider)
                        olc = repo.resolveOlcrtcConfigForConnect()
                        provider = repo.getOlcrtcProvider()
                        p = olc?.providers?.get(provider)
                    }
                    WdttTunnelManager.traceApp(
                        "olcrtc",
                        "config resolve ${olcMs()}ms room=${olc?.providers?.get(provider)?.room?.take(24)}",
                    )
                    if (p?.denied == true || (olc?.pool_denied == true && p?.room.isNullOrBlank())) {
                        val msg = olc?.pool_denied_detail?.takeIf { it.isNotBlank() }
                            ?: "Нет свободных комнат обхода. Попробуйте позже."
                        WdttTunnelManager.traceApp("olcrtc", msg, isError = true)
                        _vpnError.value = msg
                        _vpnState.value = VpnState.DISCONNECTED
                        return@launch
                    }
                    if (olc == null || !olc.enabled || olc.crypto_key.length != 64 || p == null || !p.enabled || p.room.isBlank()) {
                        // Полный fetch до ошибки — после смены провайдера кеш часто ещё пуст.
                        if (olcrtcReassignAttempt < 2) {
                            WdttTunnelManager.traceApp("olcrtc", "config miss → force fetch provider=$provider")
                            ensureOlcrtcConfigApi(context, provider)
                            val retry = repo.getCachedOlcrtcConfigForProvider(provider)
                                ?: runCatching { repo.fetchOlcrtcConfigTunnelOnly(provider) }.getOrNull()
                                ?: runCatching { repo.fetchOlcrtcConfig(provider) }.getOrNull()
                            val rp = retry?.providers?.get(provider)
                            if (retry != null && retry.enabled && retry.crypto_key.length == 64 &&
                                rp != null && rp.enabled && rp.room.isNotBlank()
                            ) {
                                WdttTunnelManager.traceApp(
                                    "olcrtc",
                                    "config force-fetch ok room=${rp.room.take(40)}",
                                )
                                _vpnError.value = null
                                _vpnState.value = VpnState.DISCONNECTED
                                delay(150)
                                connect(context, olcrtcReassignAttempt + 1)
                                return@launch
                            }
                        }
                        val msg = "Нет сессии обхода (пул/сеть). Меню → Варианты обхода → Применить, затем VPN."
                        com.silent.vpn.util.OlcrtcDiag.e(
                            com.silent.vpn.util.OlcrtcDiag.CFG,
                            "NO_SESSION provider=$provider cacheTm=${repo.getCachedOlcrtcConfigForProvider("telemost") != null} cacheWb=${repo.getCachedOlcrtcConfigForProvider("wbstream") != null} enabled=${olc?.enabled} room=${p?.room}",
                        )
                        WdttTunnelManager.traceApp("olcrtc", msg, isError = true)
                        _vpnError.value = msg
                        _vpnState.value = VpnState.DISCONNECTED
                        return@launch
                    }
                    WdttTunnelManager.traceApp(
                        "olcrtc",
                        "config ok slot=${olc.assigned_slot.ifBlank { p.room_slot_id }} room=${p.room.take(48)}",
                    )
                    val stub = loadCachedVpnConfig() ?: VpnConfig(
                        device_id = repo.getSessionDeviceId() ?: fp,
                        server_ip = "127.0.0.1",
                        server_port = 0,
                        wdtt_password = "",
                        wg_private_key = "",
                        wg_address = "",
                        wg_dns = "1.1.1.1",
                        server_public_key = "",
                        vk_hashes = emptyList(),
                        stream_count = 1,
                    )
                    DebugLog.i("MainViewModel", "connect olcrtc provider=$provider")
                    val json = org.json.JSONObject().apply {
                        put("bypass_family", "olcrtc")
                        put("bypassFamily", "olcrtc2")
                        put("olcrtc_provider", provider)
                        put("olcrtc_room", p.room)
                        put("olcrtc_crypto_key", olc.crypto_key)
                        put("olcrtc_transport", p.transport.ifBlank { "datachannel" })
                        put("olcrtc_socks_host", olc.socks_host.ifBlank { "127.0.0.1" })
                        put("olcrtc_socks_port", olc.socks_port.takeIf { it > 0 } ?: 8808)
                        if (p.auth_token.isNotBlank()) {
                            put("olcrtc_auth_token", p.auth_token)
                        }
                        // HTTPS_PROXY Улья — только Jitsi (meet.*). Telemost/WB = whitelist,
                        // auth через OkHttp на телефоне; при блоках наш VPS недоступен.
                        if (repo.isOnMobileData() &&
                            olc.jitsi_https_proxy.isNotBlank() &&
                            (p.room.contains("meet.egovm.ru") || p.room.contains("meet.playform.ru"))
                        ) {
                            put("olcrtc_https_proxy", olc.jitsi_https_proxy)
                        }
                        put("is_bootstrap", false)
                        put("device_id", stub.device_id)
                    }
                    WdttTunnelManager.clearLogs()
                    WdttTunnelManager.logUi("olcrtc_connect", "olcrtc connect provider=$provider", 1)
                    com.silent.vpn.util.OlcrtcDiag.i(
                        com.silent.vpn.util.OlcrtcDiag.CONN,
                        "connect START provider=$provider room=${p.room.take(48)} roomDbId=${p.room_db_id}",
                    )
                    olcrtcSessionProvider = provider
                    olcrtcSessionRoomDbId =
                        p.room_db_id?.trim()?.takeIf { it.isNotEmpty() }
                    repo.bindOlcrtcSession(provider, olcrtcSessionRoomDbId)
                    val intent = Intent(context, SilentVpnService::class.java).apply {
                        action = SilentVpnService.ACTION_CONNECT
                        putExtra(SilentVpnService.EXTRA_CONFIG, json.toString())
                        putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, false)
                    }
                    ContextCompat.startForegroundService(context, intent)
                    pendingConnectAfterSubscriptionRefresh = false
                    var olcOk = false
                    // Первые ~15с опрос 200мс — иначе UI отстаёт от tunnelReady до 1с.
                    for (tick in 0 until 300) {
                        delay(if (tick < 75) 200 else 500)
                        if (_vpnState.value != VpnState.CONNECTING) return@launch
                        val err = OlcrtcTunnelManager.lastError.value
                        if (err != null) {
                            _vpnError.value = err
                            WdttTunnelManager.logUi("olcrtc_fail", err, 99, isError = true)
                            // Ранний exit (WB 403 guest / бинарь) — иначе sticky на мёртвой room.
                            if (err.contains("гост", ignoreCase = true) ||
                                err.contains("мертв", ignoreCase = true) ||
                                err.contains("мёртв", ignoreCase = true) ||
                                err.contains("auth.token", ignoreCase = true) ||
                                err.contains("code=1", ignoreCase = true) ||
                                err.contains("канал", ignoreCase = true) ||
                                err.contains("без SOCKS", ignoreCase = true) ||
                                err.contains("SOCKS не поднялся", ignoreCase = true) ||
                                err.contains("not found", ignoreCase = true) ||
                                err.contains("WB join 404", ignoreCase = true) ||
                                err.contains("join room", ignoreCase = true)
                            ) {
                                if (
                                    !OlcrtcSessionPolicy.shouldWipeCacheOnEarlyFail(
                                        err,
                                        olcrtcReassignAttempt,
                                    ) &&
                                    olcrtcReassignAttempt < 1
                                ) {
                                    _vpnError.value = null
                                    _vpnState.value = VpnState.DISCONNECTED
                                    stopVpnLocally(context)
                                    delay(400)
                                    WdttTunnelManager.logUi(
                                        "olcrtc_retry",
                                        "повтор той же комнаты (stale onDestroy/code=1)",
                                        1,
                                    )
                                    connect(context, olcrtcReassignAttempt + 1)
                                    return@launch
                                }
                                var newRoom: String? = null
                                runCatching {
                                    // Не clearOlcrtcCache до нового assign — на LTE без VK
                                    // nip.io мёртв → «нет конфига, включите VK».
                                    val next = repo.reportOlcrtcRoomFailure(err)
                                    newRoom = next?.providers?.get(repo.getOlcrtcProvider())?.room
                                    if (!newRoom.isNullOrBlank()) {
                                        WdttTunnelManager.logUi(
                                            "olcrtc_reassign",
                                            "новый канал после early fail: ${newRoom.take(48)}",
                                            1,
                                        )
                                    }
                                }
                                if (!newRoom.isNullOrBlank() && olcrtcReassignAttempt < 1) {
                                    _vpnError.value = null
                                    _vpnState.value = VpnState.DISCONNECTED
                                    stopVpnLocally(context)
                                    delay(500)
                                    WdttTunnelManager.logUi(
                                        "olcrtc_retry",
                                        "авто-повтор на новой комнате (attempt=${olcrtcReassignAttempt + 1})",
                                        1,
                                    )
                                    connect(context, olcrtcReassignAttempt + 1)
                                    return@launch
                                }
                                if (newRoom.isNullOrBlank() && olcrtcReassignAttempt < 1) {
                                    // Queen :443 мёртв → ephemeral + tunnel-only, не public fetch.
                                    delay(400)
                                    ensureOlcrtcConfigApi(context, repo.getOlcrtcProvider())
                                    val late = repo.getCachedOlcrtcConfigForProvider(repo.getOlcrtcProvider())
                                    val lateRoom = late?.providers?.get(repo.getOlcrtcProvider())?.room
                                    if (!lateRoom.isNullOrBlank()) {
                                        _vpnError.value = null
                                        _vpnState.value = VpnState.DISCONNECTED
                                        stopVpnLocally(context)
                                        WdttTunnelManager.logUi(
                                            "olcrtc_retry",
                                            "авто-повтор после ensure: ${lateRoom.take(40)}",
                                            1,
                                        )
                                        connect(context, olcrtcReassignAttempt + 1)
                                        return@launch
                                    }
                                    _vpnError.value =
                                        "Канал мёртв, новый ещё не готов. Подождите 10–20 с и включите VPN снова."
                                }
                            }
                            _vpnState.value = VpnState.DISCONNECTED
                            stopVpnLocally(context)
                            return@launch
                        }
                        if (OlcrtcTunnelManager.tunnelReady.value) {
                            olcOk = true
                            break
                        }
                        if (tick == 25 || tick == 75 || tick == 150 || tick == 250) {
                            val elapsedMs =
                                if (tick < 75) tick * 200
                                else 75 * 200 + (tick - 75) * 500
                            WdttTunnelManager.logUi(
                                "olcrtc_wait",
                                "waiting peer… ${elapsedMs / 1000}s running=${OlcrtcTunnelManager.running.value}",
                            )
                        }
                    }
                    if (olcOk) {
                        _vpnState.value = VpnState.CONNECTED
                        repo.clearTunnelApiBase()
                        runCatching {
                            repo.markOlcrtcRoomConnected(
                                olc.providers[provider]?.room,
                            )
                        }
                        startOlcrtcHeartbeatLoop()
                        WdttTunnelManager.logUi("olcrtc_ok", "olcrtc connected (SOCKS)", 1)
                        return@launch
                    }
                    val fail = OlcrtcTunnelManager.lastError.value ?: "olcrtc не поднялся (бинарь/room/peer)"
                    WdttTunnelManager.logUi("olcrtc_fail", fail, 99, isError = true)
                    var newRoom: String? = null
                    runCatching {
                        val next = repo.reportOlcrtcRoomFailure(fail)
                        newRoom = next?.providers?.get(repo.getOlcrtcProvider())?.room
                        if (!newRoom.isNullOrBlank()) {
                            WdttTunnelManager.logUi(
                                "olcrtc_reassign",
                                "новый канал после failure: ${newRoom.take(48)}",
                                1,
                            )
                        }
                    }
                    if (!newRoom.isNullOrBlank() && olcrtcReassignAttempt < 1) {
                        _vpnError.value = null
                        _vpnState.value = VpnState.DISCONNECTED
                        stopVpnLocally(context)
                        delay(500)
                        WdttTunnelManager.logUi(
                            "olcrtc_retry",
                            "авто-повтор на новой комнате (attempt=${olcrtcReassignAttempt + 1})",
                            1,
                        )
                        connect(context, olcrtcReassignAttempt + 1)
                        return@launch
                    }
                    _vpnError.value = fail
                    _vpnState.value = VpnState.DISCONNECTED
                    stopVpnLocally(context)
                    return@launch
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
                    waitForTunnelReady(context, config.stream_count, relaunchConfig = config)
                    return@launch
                }

                val fetch = fetchVpnConfigForConnect(context, fp)
                var vpnConfig = fetch.vpnConfig
                val apiError = fetch.apiError
                val accessDenied = fetch.accessDenied

                if (accessDenied) {
                    pendingConnectAfterSubscriptionRefresh = true
                    _vpnState.value = VpnState.DISCONNECTED
                    _vpnError.value = null
                    _vpnError.value = apiError ?: subscriptionRequiredMessage()
                    if (!repo.isOnMobileData()) {
                        refreshWifiSubscriptionProfile()
                    } else {
                        loadProfile()
                    }
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
                waitForTunnelReady(context, toConnect.stream_count, relaunchConfig = toConnect)
            }.onFailure {
                if (!shouldSurfaceConnectFailure(it)) {
                    DebugLog.i("MainViewModel", "connect cancelled: ${it.message}")
                    if (it is CancellationException) throw it
                    return@onFailure
                }
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
        if (repo.isOlcrtcBypass()) {
            viewModelScope.launch {
                // Кеш с login/sync — без лишнего /olcrtc2-config перед стартом сервиса.
                val olc = repo.resolveOlcrtcConfigForConnect()
                val provider = repo.getOlcrtcProvider()
                val p = olc?.providers?.get(provider)
                if (olc == null || !olc.enabled || olc.crypto_key.length != 64 || p == null || !p.enabled || p.room.isBlank()) {
                    _vpnError.value =
                        olc?.pool_denied_detail?.takeIf { it.isNotBlank() }
                            ?: "Нет olcrtc2-config. Меню → Варианты обхода → Применить."
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }
                val json = org.json.JSONObject().apply {
                    put("bypass_family", "olcrtc")
                    put("bypassFamily", "olcrtc2")
                    put("olcrtc_provider", provider)
                    put("olcrtc_room", p.room)
                    put("olcrtc_crypto_key", olc.crypto_key)
                    put("olcrtc_transport", p.transport.ifBlank { "datachannel" })
                    put("olcrtc_socks_host", olc.socks_host.ifBlank { "127.0.0.1" })
                    put("olcrtc_socks_port", olc.socks_port.takeIf { it > 0 } ?: 8808)
                    if (p.auth_token.isNotBlank()) {
                        put("olcrtc_auth_token", p.auth_token)
                    }
                    if (repo.isOnMobileData() &&
                        olc.jitsi_https_proxy.isNotBlank() &&
                        (p.room.contains("meet.egovm.ru") || p.room.contains("meet.playform.ru"))
                    ) {
                        put("olcrtc_https_proxy", olc.jitsi_https_proxy)
                    }
                    put("is_bootstrap", isBootstrap)
                    put("device_id", config.device_id)
                }
                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_CONNECT
                    putExtra(SilentVpnService.EXTRA_CONFIG, json.toString())
                    putExtra(SilentVpnService.EXTRA_IS_BOOTSTRAP, isBootstrap)
                }
                ContextCompat.startForegroundService(context, intent)
            }
            return
        }
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
                DeviceRegisterRequest(repo.getDeviceDisplayName(), repo.getApiDeviceType(), fp, null, null),
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

    /** WG поднимается за 3–5 с; ждём до 45 с (капча/сеть). При flood — каскад auto→manual. */
    private suspend fun waitForTunnelReady(
        context: Context,
        @Suppress("UNUSED_PARAMETER") totalWorkers: Int,
        relaunchConfig: VpnConfig? = null,
    ) {
        repo.resetVkCredSessionEscalate()
        WdttTunnelManager.consumeFloodEscalate()

        for (attempt in 0 until 3) {
            if (attempt > 0) {
                if (relaunchConfig == null || !repo.escalateVkCredSession()) break
                val mode = repo.vkCredStrategyLabel()
                DebugLog.w("MainViewModel", "connect escalate → $mode")
                WdttTunnelManager.traceApp(
                    "connect_escalate",
                    "→ $mode${if (WdttTunnelManager.consumeFloodEscalate()) " (flood)" else ""}",
                    isError = true,
                )
                _statusMsg.value = "Запасной режим: $mode…"
                stopVpnLocally(context)
                repeat(20) {
                    if (!SilentVpnService.isRunning && !WdttTunnelManager.running.value) return@repeat
                    delay(200)
                }
                if (_vpnState.value != VpnState.CONNECTING && _vpnState.value != VpnState.DISCONNECTED) {
                    return
                }
                _vpnState.value = VpnState.CONNECTING
                launchVpnService(context, relaunchConfig)
            }

            val waitTicks = if (repo.isLegacyCaptchaStrategy()) 600 else 225
            var ready = false
            var escalateEarly = false
            for (tick in 0 until waitTicks) {
                delay(200)
                if (_vpnState.value != VpnState.CONNECTING) return
                if (WdttTunnelManager.tunnelReady.value && WdttTunnelManager.running.value) {
                    ready = true
                    break
                }
                // LEGACY_ESCALATE при 0 воркерах — не ждать 45с с n=63
                if (
                    tick >= 15 &&
                    !repo.isLegacyCaptchaStrategy() &&
                    WdttTunnelManager.activeWorkers.value < 1 &&
                    WdttTunnelManager.consumeFloodEscalate()
                ) {
                    escalateEarly = true
                    break
                }
            }
            if (_vpnState.value != VpnState.CONNECTING) return
            if (ready || WdttTunnelManager.tunnelReady.value) {
                _vpnState.value = VpnState.CONNECTED
                onVpnTunnelReady()
                return
            }

            if (relaunchConfig == null) break
            val canEscalate = when (repo.getEffectiveVkCredStrategy()) {
                SilentRepository.VK_CRED_MANUAL -> false
                else -> true
            }
            if (!canEscalate) break
            if (!escalateEarly) WdttTunnelManager.consumeFloodEscalate()
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

    private fun isCurrentSessionDevice(d: DeviceInfo, sessionId: String, fp: String): Boolean {
        val did = d.id
        if (did == sessionId) return true
        if (did.length >= 8 && sessionId.length >= 8 && (did.startsWith(sessionId) || sessionId.startsWith(did))) return true
        return fp.isNotBlank() && d.device_fingerprint?.trim() == fp
    }

    private fun markLocalDeviceOffline() {
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId() ?: return
        val fp = runCatching { repo.getDeviceFingerprint() }.getOrDefault("")
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.map { d ->
            if (isCurrentSessionDevice(d, sid, fp)) d.copy(is_connected = false) else d
        }
        val connectedCount = updated.count { it.is_connected }
        val next = p.copy(devices = updated, connected_count = connectedCount)
        _profile.value = next
        repo.saveCachedProfile(next)
    }

    private fun removeDeviceFromLocalProfile(deviceId: String) {
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.filter { it.id != deviceId }
        val next = p.copy(
            devices = updated,
            devices_count = updated.size,
            connected_count = updated.count { it.is_connected },
        )
        _profile.value = next
        repo.saveCachedProfile(next)
    }

    private fun renameDeviceInLocalProfile(deviceId: String, name: String) {
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.map { d ->
            if (d.id == deviceId) d.copy(device_name = name) else d
        }
        val next = p.copy(devices = updated)
        _profile.value = next
        repo.saveCachedProfile(next)
    }

    private fun markLocalDeviceOnline() {
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId() ?: return
        val fp = runCatching { repo.getDeviceFingerprint() }.getOrDefault("")
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.map { d ->
            if (isCurrentSessionDevice(d, sid, fp)) d.copy(is_connected = true) else d
        }
        val connectedCount = updated.count { it.is_connected }
        val next = p.copy(devices = updated, connected_count = connectedCount)
        _profile.value = next
        repo.saveCachedProfile(next)
    }

    private fun startOlcrtcHeartbeatLoop() {
        // Двойной старт (tunnelReady + connect) раньше cancel'ил job → finally leave
        // рвал комнату и чистил кеш при живом VPN («нет сессии» / зелёный труп).
        if (!com.silent.vpn.policy.OlcrtcSessionPolicy.shouldStartHeartbeat(
                alreadyActive = olcrtcHeartbeatJob?.isActive == true,
            )
        ) {
            DebugLog.d("MainViewModel", "olcrtc heartbeat already running")
            return
        }
        olcrtcHeartbeatJob?.cancel()
        olcrtcHeartbeatJob = viewModelScope.launch {
            while (isActive && _vpnState.value == VpnState.CONNECTED && repo.isOlcrtcBypass()) {
                val prov = olcrtcSessionProvider ?: repo.getOlcrtcProvider()
                val roomDbId = olcrtcSessionRoomDbId
                repo.sendOlcrtcHeartbeat(
                    online = true,
                    provider = prov,
                    roomDbId = roomDbId,
                )
                delay(30_000)
            }
            // Leave только из disconnect — shouldLeaveOnHeartbeatCancel()=false (см. OlcrtcSessionPolicyTest).
        }
    }

    private fun stopOlcrtcHeartbeatLoop() {
        olcrtcHeartbeatJob?.cancel()
        olcrtcHeartbeatJob = null
    }

    /** Остановка heartbeat + leave снимка сессии (не текущего prefs после смены канала). */
    private fun leaveOlcrtcSessionAndStopHeartbeat() {
        val session = olcrtcSessionProvider
        val roomDbId = olcrtcSessionRoomDbId
        stopOlcrtcHeartbeatLoop()
        olcrtcSessionProvider = null
        olcrtcSessionRoomDbId = null
        repo.clearOlcrtcSessionBind()
        // Без снимка не leave по prefs — иначе после Apply late-leave трёт НОВЫЙ слот.
        if (session.isNullOrBlank()) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.LEAVE,
                "skip leave — no session snapshot (уже сброшен)",
            )
            return
        }
        val target = com.silent.vpn.policy.OlcrtcSessionPolicy.resolveLeaveTarget(
            sessionProvider = session,
            sessionRoomDbId = roomDbId,
            prefsProvider = session,
        )
        viewModelScope.launch {
            runCatching {
                repo.leaveOlcrtcRoom(provider = target.provider, roomDbId = target.roomDbId)
            }
        }
    }

    fun disconnect(context: Context) {
        SessionTrace.enter("MainViewModel.disconnect")
        if (_vpnState.value == VpnState.DISCONNECTING) {
            SessionTrace.exit("MainViewModel.disconnect", "already disconnecting")
            return
        }
        if (_vpnState.value == VpnState.DISCONNECTED && !SilentVpnService.isRunning) {
            if (
                OlcrtcSessionPolicy.shouldHardResetLeftoverNative(
                    vpnServiceRunning = false,
                    nativeRunning = OlcrtcTunnelManager.running.value,
                    tunnelReady = OlcrtcTunnelManager.tunnelReady.value,
                )
            ) {
                OlcrtcTunnelManager.hardReset("disconnect_leftover")
            }
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
                // Leave в фоне с коротким таймаутом: API больше не ждёт restart 8с,
                // но на LTE leave должен уйти до stop VPN. UI не крутим дольше ~2с.
                if (repo.isOlcrtcBypass()) {
                    val target = com.silent.vpn.policy.OlcrtcSessionPolicy.resolveLeaveTarget(
                        sessionProvider = olcrtcSessionProvider,
                        sessionRoomDbId = olcrtcSessionRoomDbId,
                        prefsProvider = repo.getOlcrtcProvider(),
                    )
                    stopOlcrtcHeartbeatLoop()
                    olcrtcSessionProvider = null
                    olcrtcSessionRoomDbId = null
                    repo.clearOlcrtcSessionBind()
                    val leaveJob = launch {
                        runCatching {
                            withTimeout(2_000) {
                                repo.leaveOlcrtcRoom(
                                    provider = target.provider,
                                    roomDbId = target.roomDbId,
                                )
                            }
                        }
                    }
                    stopVpnLocally(context)
                    leaveJob.join()
                } else {
                    stopVpnLocally(context)
                }
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

    fun applyReferralDeepLink(code: String) {
        val cleaned = code.trim()
        if (cleaned.isBlank()) return
        if (repo.isLoggedIn()) return
        _pendingReferralCode.value = cleaned
        _screen.value = AppScreen.LOGIN
    }

    fun clearPendingReferralCode() {
        _pendingReferralCode.value = ""
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

    fun loadReferral(onResult: (ReferralInfo?) -> Unit) {
        viewModelScope.launch {
            runCatching {
                repo.withUserBackendApi {
                    val res = repo.getApi().getReferral()
                    if (res.isSuccessful) res.body() else null
                }
            }.onSuccess { onResult(it) }.onFailure { onResult(null) }
        }
    }

    fun renameDevice(deviceId: String, name: String, onResult: (Boolean, String?) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withUserBackendApi {
                    repo.getApi().renameDevice(deviceId, com.silent.vpn.data.DeviceRenameRequest(name))
                }
                if (res.isSuccessful) {
                    renameDeviceInLocalProfile(deviceId, name)
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
                val res = repo.withUserBackendApi { repo.getApi().deleteDevice(deviceId) }
                if (res.isSuccessful) {
                    val isCurrentSession = deviceId == repo.getSessionDeviceId()
                    if (isCurrentSession) {
                        onResult(true, "__logout__")
                    } else {
                        removeDeviceFromLocalProfile(deviceId)
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

    private suspend fun initPaymentApi(planType: String): com.silent.vpn.data.PaymentResponse {
        val res = repo.getApi().initPayment(com.silent.vpn.data.PaymentInitRequest(planType))
        if (res.isSuccessful) return res.body()!!
        throw IllegalStateException(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка оплаты")
    }

    /** onUrl(url, label) — клиент открывает url во внешнем браузере и запускает poll по label. */
    fun initPayment(planType: String, onUrl: (String, String) -> Unit, onError: (String) -> Unit) {
        viewModelScope.launch {
            if (!repo.isMainVpnTunnelUp() && repo.isOnMobileData()) {
                val ok = runEphemeralApiBootstrap(appContext, force = true) {
                    runCatching { initPaymentApi(planType) }
                        .fold(
                            onSuccess = { r -> onUrl(r.url, r.label); true },
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
            }.onSuccess { onUrl(it.url, it.label) }.onFailure { e ->
                onError(e.message ?: "Ошибка")
            }
        }
    }

    private suspend fun paymentStatusApi(label: String): String {
        val res = repo.getApi().getPaymentStatus(label)
        if (res.isSuccessful) return res.body()!!.status
        throw IllegalStateException(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка проверки оплаты")
    }

    /** Единый poll для всех клиентов: раз в 4с до completed/failed/expired или таймаута 10 мин. */
    fun startPaymentPoll(label: String) {
        paymentPollJob?.cancel()
        _paymentState.value = PaymentUiState.WAITING
        paymentPollJob = viewModelScope.launch {
            val deadline = System.currentTimeMillis() + 10 * 60 * 1000L
            while (System.currentTimeMillis() < deadline) {
                delay(4000)
                val status = runCatching {
                    if (!repo.isMainVpnTunnelUp() && repo.isOnMobileData()) {
                        var result: String? = null
                        runEphemeralApiBootstrap(appContext, force = false) {
                            result = runCatching { paymentStatusApi(label) }.getOrNull()
                            result != null
                        }
                        result
                    } else {
                        repo.withUserBackendApi { paymentStatusApi(label) }
                    }
                }.getOrNull()
                when (status) {
                    "completed" -> {
                        _paymentState.value = PaymentUiState.COMPLETED
                        refreshAccountData()
                        return@launch
                    }
                    "failed", "expired" -> {
                        _paymentState.value = PaymentUiState.FAILED
                        return@launch
                    }
                    else -> { /* pending — keep polling */ }
                }
            }
            if (_paymentState.value == PaymentUiState.WAITING) {
                _paymentState.value = PaymentUiState.TIMEOUT
            }
        }
    }

    fun resetPaymentState() {
        paymentPollJob?.cancel()
        paymentPollJob = null
        _paymentState.value = PaymentUiState.IDLE
    }

    private fun hasVpnAccess(): Boolean = hasVpnAccessForProfile(_profile.value)

    private fun hasVpnAccessForProfile(p: UserProfile?): Boolean {
        if (p == null) return true
        if (p.is_admin) return true
        return p.subscription.is_active
    }

    /** Обновить UI; при истёкшей подписке на сервере — отключить main VPN. */
    private suspend fun refreshWifiSubscriptionProfile(): Boolean {
        if (repo.isOnMobileData()) return false
        return repo.fetchAndSaveProfileViaSync().fold(
            onSuccess = { profile ->
                applyServerProfile(profile, force = true)
                DebugLog.i(
                    "MainViewModel",
                    "wifi subscription refresh active=${profile.subscription.is_active}",
                )
                true
            },
            onFailure = { e ->
                DebugLog.w("MainViewModel", "wifi subscription refresh: ${e.message}")
                false
            },
        )
    }

    private fun applyServerProfile(profile: UserProfile, force: Boolean = false) {
        if (!force && shouldDeferProfileUntilSync()) {
            repo.saveCachedProfile(profile)
            return
        }
        // Сессию удалили с сервера — не разлогиниваем: перерегистрируем устройство.
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId()
        if (!sid.isNullOrBlank() && !sid.startsWith("boot:") && profile.devices.none { it.id == sid }) {
            DebugLog.w("MainViewModel", "current session missing in profile — re-register, keep login")
            _profile.value = profile
            viewModelScope.launch {
                runCatching { recoverMissingDeviceSession() }
                    .onFailure { e -> DebugLog.w("MainViewModel", "session recover: ${e.message}") }
            }
            if (silentBootstrapSync || bootstrapVpnMode || WdttTunnelManager.isBootstrapMode()) return
            // дальше — подписка/VPN как обычно
        } else {
            _profile.value = profile
            if (silentBootstrapSync || bootstrapVpnMode || WdttTunnelManager.isBootstrapMode()) return
        }
        val hasAccess = hasVpnAccessForProfile(profile)
        val vpnFullyUp = _vpnState.value == VpnState.CONNECTED ||
            (SilentVpnService.isRunning && repo.isMainVpnApiReady())
        if (pendingConnectAfterSubscriptionRefresh && hasAccess) {
            pendingConnectAfterSubscriptionRefresh = false
            _vpnError.value = null
            if (_vpnState.value == VpnState.DISCONNECTED) {
                DebugLog.i("MainViewModel", "subscription restored — auto reconnect")
                connect(appContext)
                return
            }
            if (_vpnState.value == VpnState.CONNECTING && !SilentVpnService.isRunning) {
                DebugLog.i("MainViewModel", "subscription restored during connect — continue")
            }
        } else if (hasAccess && _vpnError.value == subscriptionRequiredMessage() && !vpnFullyUp) {
            _vpnError.value = null
        }
        if (vpnFullyUp && !hasAccess) {
            MobileSyncLog.w(
                "profile",
                "subscription inactive on server — disconnect VPN sub=${profile.subscription.plan_type}",
            )
            _vpnError.value = subscriptionRequiredMessage()
            viewModelScope.launch { disconnect(appContext) }
        }
    }

    /** Слот сессии пропал в /me — создать заново, токены не трогаем. */
    private suspend fun recoverMissingDeviceSession() {
        if (!repo.isLoggedIn()) return
        if (!repo.hasSessionFingerprint()) {
            runCatching { repo.startNewSession() }
        }
        val boot = repo.getBootstrapHash()
        val res = repo.withUserBackendApi {
            repo.getApi().registerDevice(
                DeviceRegisterRequest(
                    repo.getDeviceDisplayName(),
                    repo.getApiDeviceType(),
                    repo.getDeviceFingerprint(),
                    null,
                    boot,
                ),
            )
        }
        if (!res.isSuccessful) {
            DebugLog.w("MainViewModel", "recover session register HTTP ${res.code()}")
            return
        }
        val cfg = res.body() ?: return
        repo.saveSessionDeviceId(cfg.device_id)
        repo.cacheVpnConfig(Gson().toJson(cfg))
        _sessionDeviceId.value = cfg.device_id
        DebugLog.i("MainViewModel", "session recovered device_id=${cfg.device_id.take(8)}…")
    }

    private fun subscriptionRequiredMessage() =
        "Пробный период закончился. Оформите подписку в меню → Подписка."

    private fun isBootstrapFatalError(message: String): Boolean {
        val lower = message.lowercase()
        return lower.contains("vpn-клиент завершился") ||
            lower.contains("несовместимый wrap") ||
            lower.contains("неверный пароль") ||
            lower.contains("не найден") ||
            lower.contains("binary_error") ||
            lower.contains("circuit_breaker")
    }

    private fun isIgnoredVpnError(message: String?): Boolean {
        if (message.isNullOrBlank()) return true
        val lower = message.lowercase()
        return lower.contains("cancel") ||
            lower.contains("cancellation") ||
            lower.contains("standalonecoroutine")
    }

    private fun shouldSurfaceConnectFailure(t: Throwable): Boolean {
        if (t is CancellationException) return false
        return !isIgnoredVpnError(t.message)
    }

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
