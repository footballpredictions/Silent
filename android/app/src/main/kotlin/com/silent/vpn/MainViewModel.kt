package com.silent.vpn

import android.content.Context
import android.content.Intent
import android.net.Uri
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
import com.silent.vpn.data.HashItemDto
import com.silent.vpn.data.LoginDeviceInfo
import com.silent.vpn.data.LoginRequest
import com.silent.vpn.data.ResetPasswordRequest
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.activeServerHashes
import com.silent.vpn.data.toHashItems
import com.silent.vpn.data.PromoCheckRequest
import com.silent.vpn.data.RegisterRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.VpnConfig
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

private const val BOOTSTRAP_SESSION_MS = 2 * 60 * 1000L
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

    private val _updateInfo = MutableStateFlow<UpdateCheckResponse?>(null)
    val updateInfo: StateFlow<UpdateCheckResponse?> = _updateInfo

    private val _updateProgress = MutableStateFlow(0)
    val updateProgress: StateFlow<Int> = _updateProgress

    private val _updateDownloading = MutableStateFlow(false)
    val updateDownloading: StateFlow<Boolean> = _updateDownloading

    private val _resetPasswordToken = MutableStateFlow<String?>(null)
    val resetPasswordToken: StateFlow<String?> = _resetPasswordToken

    private val _resetPasswordSuccess = MutableStateFlow(false)
    val resetPasswordSuccess: StateFlow<Boolean> = _resetPasswordSuccess

    private val _forgotSent = MutableStateFlow(false)
    val forgotSent: StateFlow<Boolean> = _forgotSent

    val lastEmail: String get() = repo.getLastEmail().orEmpty()
    val rememberMe: Boolean get() = repo.getRememberMe()
    val repository: SilentRepository get() = repo

    private fun isHashReady(): Boolean = !repo.getBootstrapHash().isNullOrBlank()

    private fun refreshHashState() {
        _bootstrapHash.value = repo.getBootstrapHash()
        _hashReady.value = isHashReady()
    }

    /** После login удаляем временный хеш входа — главный VPN работает только с серверными. */
    private fun clearBootstrapHashAfterLogin() {
        if (!repo.isLoggedIn()) return
        if (repo.getBootstrapHash().isNullOrBlank()) return
        repo.clearBootstrapHash()
        refreshHashState()
        DebugLog.i("MainViewModel", "bootstrap hash cleared after login")
    }

    private fun clearBootstrapIfServerHashesReady(items: List<HashItemDto>) {
        if (items.activeServerHashes().isEmpty()) return
        clearBootstrapHashAfterLogin()
    }

    /** Сохранить хеш из поля и подключить bootstrap VPN. */
    fun connectForLogin(context: Context, raw: String) {
        val h = HashParser.extract(raw)
        if (h == null) {
            _statusMsg.value = "Неверный хеш. Вставьте ссылку vk.com/call/join/… или сам хеш"
            return
        }
        if (bootstrapConnectingInternal) {
            _statusMsg.value = "Подключение… подождите"
            return
        }
        if (_vpnState.value == VpnState.CONNECTED && bootstrapVpnMode) {
            val saved = repo.getBootstrapHash()?.trim().orEmpty()
            if (saved == h) {
                bootstrapContext = context.applicationContext
                restartBootstrapTimerIfNeeded()
                return
            }
            resetBootstrapDeadline()
            stopVpnLocally(context)
            bootstrapVpnMode = false
            _vpnState.value = VpnState.DISCONNECTED
        }
        repo.saveBootstrapHash(h)
        refreshHashState()
        bootstrapDeadlineMs = 0L
        if (_vpnState.value != VpnState.DISCONNECTED) {
            resetBootstrapDeadline()
            stopVpnLocally(context)
            bootstrapVpnMode = false
            _vpnState.value = VpnState.DISCONNECTED
        }
        _statusMsg.value = "Подключение к серверу через VK…"
        ensureBootstrapVpn(context)
    }

    init {
        HashFailureReporter.install { hash, errorType, message ->
            if (!repo.isLoggedIn() || bootstrapVpnMode) return@install
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
                repo.clearTokens()
                _screen.value = AppScreen.LOGIN
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
            }
        } else {
            loadTheme()
            if (SilentVpnService.isRunning && isHashReady()) {
                reconcileLoginBootstrapSession(appContext)
            }
        }
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
                    if (bootstrapVpnMode || WdttTunnelManager.isBootstrapMode()) {
                        if (!bootstrapVpnMode) bootstrapVpnMode = true
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
                        onVpnTunnelReady()
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
        if (!SilentVpnService.isRunning) {
            fetchProfileNow()
            syncServerHashes(preferPublicOnly = true)
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

    fun onReturnedToApp() {
        syncSessionOnResume()
    }

    fun onAppResumed() {
        if (!repo.isLoggedIn()) {
            reconcileLoginBootstrapSession(appContext)
        } else if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            restartBootstrapTimerIfNeeded()
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
                SessionTrace.mark("MainViewModel.syncVpnStateFromSystem", "CONNECTED attach")
                attachExistingSession()
            }
            SilentVpnService.isRunning -> {
                _vpnState.value = VpnState.CONNECTING
                SessionTrace.mark("MainViewModel.syncVpnStateFromSystem", "CONNECTING")
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
        if (_resetPasswordToken.value != null) {
            SessionTrace.exit("MainViewModel.syncSessionOnResume", "reset password flow")
            _screen.value = AppScreen.LOGIN
            reconcileLoginBootstrapSession(appContext)
            return
        }
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
            if (
                _profile.value == null &&
                repo.isLoggedIn() &&
                _vpnState.value == VpnState.DISCONNECTED &&
                !VpnSessionState.isBusy()
            ) {
                runCatching {
                    if (bootstrapVpnMode && SilentVpnService.isRunning) {
                        withBootstrapBackendApi { fetchProfileNow() }
                        if (_profile.value != null) {
                            disconnectBootstrapVpn(appContext)
                        }
                    } else {
                        fetchProfileNow()
                    }
                }.onFailure { e ->
                    DebugLog.w("MainViewModel", "resume profile fetch: ${e.message}")
                }
            }
            if (SilentVpnService.isRunning && VpnSessionState.isActive()) {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _vpnState.value = VpnState.CONNECTED
                }
                // Без overlay-обновления при resume — данные из кеша; свежие приходят при connect.
            }
        }
        SessionTrace.exit("MainViewModel.syncSessionOnResume", "vpn=${_vpnState.value}")
    }

    /** Если API недоступен без VPN (белые списки) — краткий bootstrap для профиля и хешей. */
    private suspend fun refreshDataWithBootstrapFallback(context: Context) {
        repo.clearTunnelApiBase()
        if (fetchProfileNow()) {
            if (repo.isLoggedIn()) syncServerHashes()
            return
        }
        if (!repo.isLoggedIn() || !isHashReady()) return
        if (SilentVpnService.isRunning || WdttTunnelManager.running.value) return
        runSilentBootstrapSync(context)
    }

    private suspend fun runSilentBootstrapSync(context: Context) {
        if (silentBootstrapSync) return
        silentBootstrapSync = true
        try {
            val boot = HashParser.extract(repo.getBootstrapHash().orEmpty()) ?: return
            val fp = repo.getOrCreatePreLoginFingerprint()
            var config = runCatching {
                val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(boot, "android", fp))
                if (res.isSuccessful) bootstrapLaunchConfig(res.body()!!) else null
            }.getOrNull()
            if (config == null || config.vk_hashes.isEmpty()) {
                config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))
            }
            if (config.vk_hashes.isEmpty()) return
            DebugLog.i("MainViewModel", "silent bootstrap sync start")
            launchVpnService(context.applicationContext, config, forceBootstrap = true)
            repeat(60) {
                delay(200)
                if (WdttTunnelManager.tunnelReady.value) {
                    onVpnTunnelReady(config)
                    fetchProfileNow()
                    syncServerHashes()
                    refreshVpnConfigInBackground(repo.getDeviceFingerprint())
                    return
                }
            }
        } catch (e: Exception) {
            DebugLog.w("MainViewModel", "silent bootstrap sync: ${e.message}")
        } finally {
            stopVpnLocally(context.applicationContext)
            repo.clearTunnelApiBase()
            silentBootstrapSync = false
        }
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
    /** До завершения VpnBackendSync не дергаем overlay из polling. */
    private var backendSyncCompleted: Boolean
        get() = VpnSessionState.backendSyncCompleted
        set(value) { VpnSessionState.backendSyncCompleted = value }
    private val pendingHashFailures = ConcurrentLinkedQueue<Triple<String, String, String>>()
    private var hashFailureFlushJob: Job? = null

    private fun flushPendingHashFailures() {
        if (pendingHashFailures.isEmpty() || !repo.isLoggedIn()) return
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
        restoreCachedThemeToUi()
        if (!bootstrapVpnMode && repo.isLoggedIn()) {
            watchTunnelDataSyncFromCache()
        }
        if (!bootstrapVpnMode && !WdttTunnelManager.isBootstrapMode()) {
            checkForAppUpdate()
        }
    }

    private fun watchTunnelDataSyncFromCache() {
        if (VpnSessionState.tunnelDataSyncCompleted) {
            restoreCachedProfileToUi()
            restoreCachedThemeToUi(refreshFromSync = true)
            refreshHashState()
            markLocalDeviceOnline()
            backendSyncCompleted = true
            flushPendingHashFailures()
            return
        }
        tunnelSyncWatchJob?.cancel()
        tunnelSyncWatchJob = viewModelScope.launch {
            repeat(120) {
                if (VpnSessionState.tunnelDataSyncCompleted) {
                    restoreCachedProfileToUi()
                    restoreCachedThemeToUi(refreshFromSync = true)
                    refreshHashState()
                    markLocalDeviceOnline()
                    backendSyncCompleted = true
                    flushPendingHashFailures()
                    return@launch
                }
                if (_vpnState.value != VpnState.CONNECTED && !VpnSessionState.isActive()) return@launch
                delay(500)
            }
        }
    }

    private var updateCheckInFlight = false

    /** Проверка OTA: public HTTPS, затем tunnel если VPN поднят (бэкенд может быть заблокирован без VPN). */
    fun checkForAppUpdate() {
        if (updateCheckInFlight) return
        updateCheckInFlight = true
        viewModelScope.launch {
            try {
                val version = com.silent.vpn.BuildConfig.VERSION_NAME
                var ok = false
                val bases = listOf(
                    repo.getPublicServerUrl().trimEnd('/'),
                    "https://${SilentRepository.DEFAULT_SERVER_HOST}",
                ).distinct()
                for (base in bases) {
                    ok = runCatching { tryCheckUpdateOnBase(base, version) }.getOrDefault(false)
                    if (ok) break
                }
                if (!ok) {
                    tryCheckUpdateViaTunnel(version)
                }
            } catch (e: Exception) {
                DebugLog.w("MainViewModel", "checkUpdate: ${e.message}")
            } finally {
                updateCheckInFlight = false
            }
        }
    }

    /**
     * Экран «Устройства»: при включённом основном VPN — ОДНО чтение профиля (один overlay),
     * без живого 10-секундного поллинга (он дёргал WG). При выключенном VPN — обычный поллинг
     * по public API.
     */
    fun setSessionsScreenActive(active: Boolean) {
        profilePollJob?.cancel()
        profilePollJob = null
        if (!active) return
        val mainVpnUp = SilentVpnService.isRunning && !bootstrapVpnMode
        profilePollJob = viewModelScope.launch {
            while (true) {
                if (!sessionsFetchInFlight) {
                    sessionsFetchInFlight = true
                    runCatching { fetchProfileNow(force = true) }
                        .onFailure { e -> DebugLog.w("MainViewModel", "sessions poll: ${e.message}") }
                    sessionsFetchInFlight = false
                }
                if (mainVpnUp) break
                delay(SESSIONS_POLL_MS)
            }
        }
    }

    /** Профиль приходит из initial sync при connect + кеша — без периодических overlay. */
    fun setVpnProfilePolling(active: Boolean) {
        // No-op: периодический поллинг убран, чтобы не дёргать WG overlay.
    }

    /** Главный экран: проверка OTA (public, при VPN — повтор через tunnel). */
    fun setUpdatePolling(active: Boolean) {
        if (active) checkForAppUpdate()
    }

    private suspend fun tryCheckUpdateViaTunnel(version: String): Boolean {
        if (!SilentVpnService.isRunning || !WdttTunnelManager.tunnelReady.value) return false
        if (WdttTunnelManager.isBootstrapMode()) return false
        repo.prepareTunnelApiFromCachedConfig()
        return runCatching {
            repo.withBackendApi {
                tryCheckUpdateViaRepoApi(version)
            }
        }.onFailure { e ->
            DebugLog.w("MainViewModel", "checkUpdate tunnel: ${e.message}")
        }.getOrDefault(false)
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
        if (bootstrapVpnMode && WdttTunnelManager.tunnelReady.value && SilentVpnService.isRunning) {
            ensureTunnelApiBaseForLogin()
            return block()
        }
        if (needsPreLoginApiOverlay()) {
            if (!bootstrapVpnMode && _screen.value == AppScreen.LOGIN) {
                bootstrapVpnMode = true
            }
            return WdttTunnelManager.withApiOverlay {
                repo.useApiBase(WdttTunnelManager.tunnelApiBase())
                block()
            }
        }
        return block()
    }

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

    /** Шаг 1 для входа / регистрации / сброса пароля при блокировке. */
    fun ensureBootstrapForAuthFlow(context: Context) {
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
            WdttTunnelManager.isApiOverlayActive()
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
            if (WdttTunnelManager.isWorkerRampUpActive() || WdttTunnelManager.isApiOverlayActive()) {
                return _profile.value != null
            }
            return runCatching {
                repo.withBackendApi { tryFetchProfileViaRepoApi() }
            }.getOrDefault(false) || _profile.value != null
        }
        if (SilentVpnService.isRunning && !bootstrapVpnMode) {
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
        return _profile.value != null
    }

    private suspend fun tryFetchProfileViaRepoApi(): Boolean {
        try {
            val res = repo.getApi().getProfile()
            if (res.isSuccessful) {
                val p = res.body()!!
                _profile.value = p
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

    private suspend fun tryCheckUpdateViaRepoApi(version: String): Boolean {
        val res = repo.getApi().checkUpdate("android", version)
        if (!res.isSuccessful) {
            DebugLog.w("MainViewModel", "checkUpdate HTTP ${res.code()} on ${repo.getServerUrl()}")
            return false
        }
        val body = res.body()
        if (body?.available == true) {
            _updateInfo.value = body
            updateApiBaseUrl = repo.getServerUrl().trimEnd('/')
            DebugLog.i("MainViewModel", "checkUpdate: available ${body.version}")
        } else {
            _updateInfo.value = null
            DebugLog.i("MainViewModel", "checkUpdate: up to date v=$version")
        }
        return true
    }

    private suspend fun tryFetchProfileOnBase(base: String): Boolean {
        try {
            repo.useApiBase(base)
            val res = repo.getApi().getProfile()
            if (res.isSuccessful) {
                val p = res.body()!!
                _profile.value = p
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

    fun handleDeepLink(uri: Uri?, context: Context? = null) {
        val token = extractResetPasswordToken(uri) ?: return
        _resetPasswordToken.value = token
        _screen.value = AppScreen.LOGIN
        context?.let { reconcileLoginBootstrapSession(it) }
    }

    private fun extractResetPasswordToken(uri: Uri?): String? {
        if (uri == null) return null
        if (uri.scheme == "silentvpn" && uri.host == "reset-password") {
            return uri.getQueryParameter("token")?.takeIf { it.isNotBlank() }
        }
        val path = uri.path ?: return null
        if ((uri.scheme == "https" || uri.scheme == "http") && path.contains("app-reset")) {
            return uri.getQueryParameter("token")?.takeIf { it.isNotBlank() }
        }
        return null
    }

    fun clearResetToken() {
        _resetPasswordToken.value = null
        _resetPasswordSuccess.value = false
    }

    fun clearResetPasswordSuccess() {
        _resetPasswordSuccess.value = false
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

    fun resetPassword(token: String, newPassword: String) {
        viewModelScope.launch {
            reconcileLoginBootstrapSession(appContext)
            _authLoading.value = true
            _authError.value = null
            try {
                if (!_bootstrapReady.value) {
                    _authError.value = "Сначала подключитесь для входа (шаг 1)"
                    return@launch
                }
                awaitTunnelApiReady()
                val res = withBootstrapBackendApi {
                    repo.getApi().resetPassword(ResetPasswordRequest(token, newPassword))
                }
                if (!res.isSuccessful) {
                    _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Не удалось сохранить пароль"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                _resetPasswordToken.value = null
                _resetPasswordSuccess.value = true
                _authError.value = null
                refreshBootstrapCountdownNow()
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка"
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
            _resetPasswordSuccess.value = false
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
                        repo.saveRememberMe(email, rememberMe)
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
                        repo.saveRememberMe(email, rememberMe)
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
        if (!skipProfileFetch && _profile.value == null) {
            loadProfile()
        }
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
            _resetPasswordToken.value != null ->
                "Смена пароля через VPN. Осталось %d:%02d".format(mm, ss)
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
        _vpnState.value = VpnState.DISCONNECTED
        _statusMsg.value =
            "Время временного интернета истекло (2 мин). Нажмите «Подключить для входа» снова."
        updateBootstrapReadyFlag()
    }

    /** Bootstrap VPN on login screen — reach backend through user's VK hash. */
    fun ensureBootstrapVpn(context: Context) {
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
                        _statusMsg.value = "Неверный сохранённый хеш. Вставьте ссылку vk.com/call/join/… заново"
                        return@launch
                    }
                repo.saveBootstrapHash(boot)
                val fp = repo.getOrCreatePreLoginFingerprint()
                val config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))

                if (config.vk_hashes.isEmpty()) {
                    _statusMsg.value = "Нет VK-хеша для bootstrap"
                    return@launch
                }
                bootstrapVpnMode = true
                bootstrapContext = context.applicationContext
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
                        ?: "Интернет через VPN не поднялся. Проверьте хеш и попробуйте снова."
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
            val pendingReset = _resetPasswordToken.value != null
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
            repo.clearTunnelApiBase()
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
            _resetPasswordSuccess.value = false
            if (pendingReset && context != null) {
                ensureBootstrapForAuthFlow(context)
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
        if (_vpnState.value == VpnState.CONNECTING) {
            DebugLog.i("MainViewModel", "connect: cancel stale CONNECTING and retry")
            connectJob?.cancel()
            connectJob = null
        }
        if (VpnSessionState.isActive()) {
            SessionTrace.mark("MainViewModel.connect", "attach existing session")
            DebugLog.i("MainViewModel", "connect attach — shared session already active")
            _vpnState.value = VpnState.CONNECTED
            _vpnError.value = null
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
        connectJob = viewModelScope.launch {
            DebugLog.i("MainViewModel", "connect() start")
            bootstrapVpnMode = false
            backendSyncCompleted = false
            if (VpnNetworkHelper.isOtherVpnActive(context)) {
                DebugLog.i("MainViewModel", "Подключение заменит другой активный VPN")
            }
            _vpnState.value = VpnState.CONNECTING
            _vpnError.value = null
            try {
            runCatching {
                restoreCachedProfileToUi()
                if (!hasVpnAccess()) {
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

                var vpnConfig: VpnConfig? = null
                var apiError: String? = null
                var accessDenied = false

                coroutineScope {
                    val regJob = async {
                        runCatching {
                            repo.getApi().registerDevice(
                                DeviceRegisterRequest(repo.getDeviceDisplayName(), "android", fp, null, null)
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
                                _vpnError.value = parseError(regRes.errorBody()?.string() ?: "")
                                    ?: subscriptionRequiredMessage()
                                _vpnState.value = VpnState.DISCONNECTED
                                accessDenied = true
                                loadProfile()
                                return@coroutineScope
                            }
                        }
                        if (regRes.isSuccessful) {
                            vpnConfig = regRes.body()!!
                            DebugLog.i("MainViewModel", "device/register OK device=${vpnConfig!!.device_id.take(8)} hashes=${vpnConfig!!.vk_hashes.size}")
                            repo.saveSessionDeviceId(vpnConfig!!.device_id)
                            _sessionDeviceId.value = vpnConfig!!.device_id
                            repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                        } else if (regRes.code() != 0) {
                            apiError = parseError(regRes.errorBody()?.string() ?: "") ?: "Ошибка регистрации устройства"
                        }
                    }

                    if (vpnConfig == null) {
                        runCatching {
                            val cfgRes = repo.getApi().getConfig(fp)
                            if (cfgRes.isSuccessful) {
                                vpnConfig = cfgRes.body()!!
                                repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                            } else if (cfgRes.code() == 402) {
                                apiError = parseError(cfgRes.errorBody()?.string() ?: "")
                                    ?: subscriptionRequiredMessage()
                            }
                        }
                    }

                    if (vpnConfig == null) {
                        vpnConfig = loadCachedVpnConfig()
                    }

                    hashesJob.await()?.let { hres ->
                        if (hres.isSuccessful) {
                            val body = hres.body()
                            val hashItems = body?.toHashItems().orEmpty()
                            if (hashItems.isNotEmpty()) {
                                repo.saveHashItems(hashItems)
                                clearBootstrapIfServerHashesReady(hashItems)
                            }
                            val serverHashes = hashItems.activeServerHashes().map { it.hash }
                            if (serverHashes.isNotEmpty() && vpnConfig != null) {
                                vpnConfig = vpnConfig!!.copy(
                                    vk_hashes = serverHashes.take(HashChannelHelper.MAX_HASHES),
                                )
                                repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                                if (serverHashes.size < HashChannelHelper.MAX_HASHES) {
                                    runCatching {
                                        repo.getApi().requestHashRefresh(ConnectRequest(fp, "android"))
                                    }
                                }
                            }
                        }
                    }
                }

                if (accessDenied) return@launch

                if (vpnConfig == null) {
                    DebugLog.e("MainViewModel", apiError ?: "no vpn config")
                    _vpnError.value = apiError ?: "Сервер недоступен. Подключитесь дома по Wi‑Fi для первого входа."
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                if (!isConfigConnectable(vpnConfig!!)) {
                    _vpnError.value = when {
                        !repo.hasMainVpnServerHashes() && repo.resolveConnectVkHashes(vpnConfig!!.vk_hashes).isEmpty() ->
                            "Нет серверных хешей. Перезайдите в аккаунт."
                        vpnConfig!!.vk_hashes.isEmpty() -> "Нет VK-хеша. Введите хеш на экране входа."
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
            config.server_public_key.isNotBlank()

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
        repo.saveCachedProfile(_profile.value!!)
    }

    private fun markLocalDeviceOnline() {
        val sid = _sessionDeviceId.value ?: repo.getSessionDeviceId() ?: return
        val p = _profile.value ?: repo.getCachedProfile() ?: return
        val updated = p.devices.map { d ->
            if (d.id == sid) d.copy(is_connected = true) else d
        }
        val connectedCount = updated.count { it.is_connected }
        _profile.value = p.copy(devices = updated, connected_count = connectedCount)
        repo.saveCachedProfile(_profile.value!!)
    }

    fun disconnect(context: Context) {
        SessionTrace.enter("MainViewModel.disconnect")
        if (_vpnState.value == VpnState.DISCONNECTED && !SilentVpnService.isRunning) {
            SessionTrace.exit("MainViewModel.disconnect", "already off")
            return
        }
        connectJob?.cancel()
        connectJob = null
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
        _vpnState.value = VpnState.DISCONNECTED
        stopVpnLocally(context)
        SessionTrace.exit("MainViewModel.disconnect")
    }

    fun checkPromo(code: String, onResult: (String) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withBackendApi {
                    repo.getApi().checkPromo(PromoCheckRequest(code, "monthly"))
                }
                if (res.isSuccessful) {
                    onResult("Скидка ${res.body()!!.discount_percent}%!")
                } else {
                    onResult(parseError(res.errorBody()?.string() ?: "") ?: "Не найден")
                }
            }.onFailure {
                onResult(it.message ?: "Ошибка")
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

    fun initPayment(planType: String, onUrl: (String) -> Unit, onError: (String) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withBackendApi {
                    repo.getApi().initPayment(com.silent.vpn.data.PaymentInitRequest(planType))
                }
                if (res.isSuccessful) onUrl(res.body()!!.url)
                else onError(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка оплаты")
            }.onFailure {
                onError(it.message ?: "Ошибка")
            }
        }
    }

    private fun hasVpnAccess(): Boolean {
        val p = _profile.value ?: return true
        if (p.is_admin) return true
        return p.subscription.is_active
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
