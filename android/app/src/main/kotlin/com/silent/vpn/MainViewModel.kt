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
import com.silent.vpn.data.LoginRequest
import com.silent.vpn.data.ResetPasswordRequest
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.activeServerHashes
import com.silent.vpn.data.prepareVpnConnectConfig
import com.silent.vpn.data.toHashItems
import com.silent.vpn.data.PromoCheckRequest
import com.silent.vpn.data.RegisterRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.vk.HashParser
import com.silent.vpn.util.DebugLog
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
import kotlinx.coroutines.delay
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import javax.inject.Inject

private const val BOOTSTRAP_SESSION_MS = 2 * 60 * 1000L
/** Пока VPN включён — периодически спрашиваем сервер о новой версии. */
private const val UPDATE_POLL_INTERVAL_MS = 120_000L
private const val VPN_PROFILE_POLL_INTERVAL_MS = 60_000L

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

    private val _sessionDeviceId = MutableStateFlow(repo.getSessionDeviceId())
    val sessionDeviceId: StateFlow<String?> = _sessionDeviceId

    private var bootstrapVpnMode = false
    private var bootstrapConnectingInternal = false
    private var bootstrapTimeoutJob: Job? = null
    private var bootstrapContext: Context? = null
    private var silentBootstrapSync = false
    private var profilePollJob: Job? = null
    private var vpnProfilePollJob: Job? = null
    private var updatePollJob: Job? = null
    private var updateApiBaseUrl: String? = null
    private var onlineHeartbeatJob: Job? = null

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

    /** Удаляем bootstrap только если с сервера есть ≥1 активный хеш; иначе — fallback для главного VPN. */
    private fun clearBootstrapIfServerHashesReady(items: List<HashItemDto>) {
        val active = items.activeServerHashes()
        if (active.isEmpty()) return
        if (repo.getBootstrapHash().isNullOrBlank()) return
        repo.saveBootstrapHash(null)
        refreshHashState()
        DebugLog.i("MainViewModel", "bootstrap cleared (${active.size} server hash(es))")
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
            bootstrapContext = context.applicationContext
            restartBootstrapTimerIfNeeded()
            return
        }
        repo.saveBootstrapHash(h)
        refreshHashState()
        if (_vpnState.value != VpnState.DISCONNECTED) {
            cancelBootstrapSessionTimeout()
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
            repo.reportHashFailure(hash, errorType, message)
                .onFailure { e -> DebugLog.w("MainViewModel", "hash failure report: ${e.message}") }
        }
        if (repo.isLoggedIn()) {
            if (!repo.hasSessionFingerprint()) {
                repo.clearTokens()
                _screen.value = AppScreen.LOGIN
            } else {
                _screen.value = AppScreen.MAIN
                restoreCachedProfileToUi()
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
        }
        viewModelScope.launch {
            WdttTunnelManager.lastError.collect { err ->
                if (!err.isNullOrBlank() &&
                    (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.CONNECTED)
                ) {
                    DebugLog.e("MainViewModel", "WDTT error: $err")
                    _vpnError.value = err
                    _vpnState.value = VpnState.DISCONNECTED
                    if (bootstrapVpnMode) {
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
                    if (!WdttTunnelManager.isInternetReady() &&
                        WdttTunnelManager.activeWorkers.value < 1
                    ) {
                        return@collect
                    }
                    if (bootstrapVpnMode) {
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady()
                        bootstrapContext?.let { startBootstrapSessionTimeout(it) }
                    } else if (silentBootstrapSync) {
                        onVpnTunnelReady()
                    } else if (SilentVpnService.isRunning) {
                        if (!repo.isLoggedIn() && _screen.value == AppScreen.LOGIN) {
                            bootstrapVpnMode = true
                        }
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady()
                    }
                } else if (
                    (_vpnState.value == VpnState.CONNECTED || _vpnState.value == VpnState.DISCONNECTING) &&
                    !WdttTunnelManager.running.value &&
                    WdttTunnelManager.activeWorkers.value < 1
                ) {
                    onlineHeartbeatJob?.cancel()
                    onlineHeartbeatJob = null
                    _vpnState.value = VpnState.DISCONNECTED
                    repo.clearTunnelApiBase()
                }
            }
        }
    }

    private suspend fun refreshSession() {
        loadTheme()
        fetchProfileNow()
        syncServerHashes()
    }

    /** Профиль и хеши через bootstrap-туннель до отключения временного VPN. */
    private suspend fun syncLoginDataViaBootstrapTunnel(): Boolean {
        if (!WdttTunnelManager.isInternetReady()) return false
        val tunnel = WdttTunnelManager.tunnelApiBase()
        repo.useApiBase(tunnel)
        runCatching {
            val reg = repo.getApi().registerDevice(
                DeviceRegisterRequest("Android", "android", repo.getDeviceFingerprint(), null, repo.getBootstrapHash())
            )
            if (reg.isSuccessful) {
                val cfg = reg.body()!!
                repo.saveSessionDeviceId(cfg.device_id)
                _sessionDeviceId.value = cfg.device_id
                repo.cacheVpnConfig(Gson().toJson(cfg))
                DebugLog.i("MainViewModel", "login cache device=${cfg.device_id.take(8)} hashes=${cfg.vk_hashes.size}")
            }
        }.onFailure { e ->
            DebugLog.w("MainViewModel", "login registerDevice cache: ${e.message}")
        }
        val items = runCatching {
            repo.fetchAndSaveHashItemsViaTunnel().getOrDefault(emptyList())
        }.getOrElse {
            DebugLog.w("MainViewModel", "login hash sync: ${it.message}")
            repo.getSavedHashItems()
        }
        clearBootstrapIfServerHashesReady(items)
        return fetchProfileNow() || _profile.value != null
    }

    fun onReturnedToApp() {
        syncSessionOnResume()
    }

    fun onAppResumed() {
        if (!repo.isLoggedIn() && bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            restartBootstrapTimerIfNeeded()
        }
        syncSessionOnResume()
    }

    private fun restoreCachedProfileToUi() {
        repo.getCachedProfile()?.let { cached ->
            if (_profile.value == null) _profile.value = cached
        }
    }

    private fun syncVpnStateFromSystem() {
        when {
            SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value -> {
                _vpnState.value = VpnState.CONNECTED
                onVpnTunnelReady()
            }
            SilentVpnService.isRunning -> _vpnState.value = VpnState.CONNECTING
            else -> _vpnState.value = VpnState.DISCONNECTED
        }
    }

    private fun syncSessionOnResume() {
        if (_resetPasswordToken.value != null) {
            _screen.value = AppScreen.LOGIN
            ensureBootstrapForAuthFlow(appContext)
            return
        }
        if (!repo.isLoggedIn()) return
        _screen.value = AppScreen.MAIN
        _authLoading.value = false
        restoreCachedProfileToUi()
        syncVpnStateFromSystem()
        viewModelScope.launch {
            if (_profile.value == null && repo.isLoggedIn()) {
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
            if (SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) {
                onVpnTunnelReady()
                if (_vpnState.value == VpnState.CONNECTED && repo.isLoggedIn()) {
                    runCatching { checkForUpdateNow() }
                }
            }
        }
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
            launchVpnService(context.applicationContext, config)
            repeat(60) {
                delay(200)
                if (WdttTunnelManager.tunnelReady.value && WdttTunnelManager.isInternetReady()) {
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
    private suspend fun syncServerHashes(): List<HashItemDto> {
        val result = repo.fetchAndSaveHashItems()
        if (result.isFailure) {
            Log.w("MainViewModel", "syncServerHashes: ${result.exceptionOrNull()?.message}")
            return repo.getSavedHashItems()
        }
        val items = result.getOrDefault(emptyList())
        clearBootstrapIfServerHashesReady(items)
        return items
    }

    private var mainTunnelDataSyncJob: Job? = null
    private var backendSyncJob: Job? = null
    private var connectJob: Job? = null

    private fun onVpnTunnelReady(vpnConfig: VpnConfig? = null) {
        if (_vpnState.value == VpnState.DISCONNECTING) return
        val wgAddr = vpnConfig?.wg_address?.takeIf { it.isNotBlank() }
            ?: loadCachedVpnConfig()?.wg_address?.takeIf { it.isNotBlank() }
            ?: WdttTunnelManager.lastWgAddress()
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) {
            repo.setTunnelApiFromWgAddress(wgAddr)
        } else {
            repo.clearTunnelApiBase()
        }
        if (repo.isLoggedIn() && !bootstrapVpnMode && SilentVpnService.isRunning) {
            backendSyncJob?.cancel()
            backendSyncJob = viewModelScope.launch {
                WdttTunnelManager.awaitWgConfigSettled()
                if (_vpnState.value != VpnState.CONNECTED || !WdttTunnelManager.tunnelReady.value) return@launch
                markDeviceOnlineOnServer()
                triggerUpdateCheckAndPolling()
                runCatching { fetchProfileNow() }
                    .onFailure { e -> DebugLog.w("MainViewModel", "profile after tunnel ready: ${e.message}") }
            }
        } else {
            loadTheme()
        }
    }

    /** Сразу проверить обновление и держать фоновый опрос, пока VPN подключён. */
    private fun triggerUpdateCheckAndPolling() {
        if (_vpnState.value != VpnState.CONNECTED || bootstrapVpnMode || !repo.isLoggedIn()) return
        startUpdatePolling()
    }

    private fun startUpdatePolling() {
        if (updatePollJob?.isActive == true) return
        updatePollJob = viewModelScope.launch {
            delay(5_000)
            while (
                _vpnState.value == VpnState.CONNECTED &&
                repo.isLoggedIn() &&
                !bootstrapVpnMode &&
                SilentVpnService.isRunning
            ) {
                runCatching { checkForUpdateNow() }
                delay(UPDATE_POLL_INTERVAL_MS)
            }
        }
    }

    private fun stopUpdatePolling(clearBanner: Boolean = true) {
        updatePollJob?.cancel()
        updatePollJob = null
        if (clearBanner) {
            _updateInfo.value = null
            updateApiBaseUrl = null
        }
    }

    private fun markDeviceOnlineOnServer() {
        if (_vpnState.value != VpnState.CONNECTED) return
        onlineHeartbeatJob?.cancel()
        onlineHeartbeatJob = viewModelScope.launch {
            var intervalMs = 0L
            while (_vpnState.value == VpnState.CONNECTED && SilentVpnService.isRunning) {
                if (intervalMs > 0L) delay(intervalMs)
                val ok = runCatching {
                    repo.withTunnelApiWhenExcluded {
                        val res = repo.getApi().connect(
                            ConnectRequest(repo.getDeviceFingerprint(), "android"),
                        )
                        if (!res.isSuccessful) {
                            throw Exception("online HTTP ${res.code()}: ${res.errorBody()?.string()?.take(120)}")
                        }
                    }
                }.onSuccess {
                    DebugLog.i("MainViewModel", "online heartbeat OK (tunnel API)")
                }.onFailure { e ->
                    DebugLog.w("MainViewModel", "online heartbeat: ${e.message}")
                }.isSuccess
                intervalMs = if (ok) 5 * 60 * 1000L else 30_000L
            }
        }
    }

    /** Периодическое обновление списка сессий, пока открыт экран «Сессии» (как на PC, 5 с). */
    fun setSessionsScreenActive(active: Boolean) {
        profilePollJob?.cancel()
        profilePollJob = null
        if (!active) return
        loadProfile()
        profilePollJob = viewModelScope.launch {
            while (true) {
                delay(5000)
                runCatching { fetchProfileNow() }
            }
        }
    }

    /** Обновление профиля каждые 10 с при активном VPN на главном экране (как на PC). */
    fun setVpnProfilePolling(active: Boolean) {
        vpnProfilePollJob?.cancel()
        vpnProfilePollJob = null
        if (!active) return
        vpnProfilePollJob = viewModelScope.launch {
            while (true) {
                delay(VPN_PROFILE_POLL_INTERVAL_MS)
                runCatching { fetchProfileNow() }
            }
        }
    }

    /** Проверка обновлений через VPN (как на PC). */
    fun setUpdatePolling(active: Boolean) {
        if (!active) {
            stopUpdatePolling(clearBanner = true)
            return
        }
        triggerUpdateCheckAndPolling()
    }

    private suspend fun checkForUpdateNow() {
        if (_vpnState.value != VpnState.CONNECTED) {
            stopUpdatePolling(clearBanner = true)
            return
        }
        if (!SilentVpnService.isRunning || bootstrapVpnMode || !repo.isLoggedIn()) return
        if (SilentRepository.APP_EXCLUDED_FROM_VPN && !WdttTunnelManager.tunnelReady.value) {
            return
        }
        val version = AppUpdateManager.currentVersion()
        if (
            SilentVpnService.isRunning &&
            !bootstrapVpnMode &&
            SilentRepository.APP_EXCLUDED_FROM_VPN &&
            WdttTunnelManager.tunnelReady.value
        ) {
            runCatching {
                repo.withTunnelApiWhenExcluded {
                    tryCheckUpdateOnBase(repo.tunnelApiBaseUrl(), version)
                }
            }.onFailure { e ->
                DebugLog.w("MainViewModel", "checkUpdate: ${e.message}")
            }
            return
        }
        val bases = when {
            SilentVpnService.isRunning && bootstrapVpnMode && WdttTunnelManager.tunnelReady.value ->
                listOf(WdttTunnelManager.tunnelApiBase())
            else -> repo.apiBaseCandidates(WdttTunnelManager.lastWgAddress())
        }
        for (base in bases) {
            try {
                if (SilentVpnService.isRunning && bootstrapVpnMode && WdttTunnelManager.tunnelReady.value) {
                    val ok = WdttTunnelManager.withApiOverlay {
                        tryCheckUpdateOnBase(base, version)
                    }
                    if (ok) return
                } else {
                    if (tryCheckUpdateOnBase(base, version)) return
                }
            } catch (e: Exception) {
                DebugLog.w("MainViewModel", "checkUpdate: ${e.message}")
            }
        }
    }

    private suspend fun tryCheckUpdateOnBase(base: String, version: String): Boolean {
        repo.useApiBase(base)
        val res = repo.getApi().checkUpdate("android", version)
        if (!res.isSuccessful) return false
        val body = res.body()
        if (body?.available == true) {
            _updateInfo.value = body
            updateApiBaseUrl = base.trimEnd('/')
        } else {
            _updateInfo.value = null
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
                val file = AppUpdateManager.downloadApk(
                    context,
                    url,
                    info.filename ?: "update.apk",
                    repo.buildDownloadClient(),
                ) { pct -> _updateProgress.value = pct }
                onInstallReady(AppUpdateManager.installApk(context, file))
            } catch (e: Exception) {
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
        if (needsPreLoginApiOverlay()) {
            return listOf(WdttTunnelManager.tunnelApiBase())
        }
        return repo.apiBaseCandidates(WdttTunnelManager.lastWgAddress())
    }

    /** Шаг 1 для входа / регистрации / сброса пароля при блокировке. */
    fun ensureBootstrapForAuthFlow(context: Context) {
        if (!isHashReady()) return
        if (SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) {
            if (!bootstrapVpnMode) bootstrapVpnMode = true
            bootstrapContext = context.applicationContext
            if (_vpnState.value != VpnState.CONNECTED) {
                _vpnState.value = VpnState.CONNECTED
                onVpnTunnelReady()
            }
            restartBootstrapTimerIfNeeded()
            return
        }
        if (_vpnState.value != VpnState.CONNECTING && !bootstrapConnectingInternal) {
            ensureBootstrapVpn(context)
        }
    }

    private suspend fun fetchProfileNow(): Boolean {
        // Основной VPN: app вне WG (TURN напрямую), API — через overlay 10.66.66.0/24.
        if (SilentVpnService.isRunning && !bootstrapVpnMode) {
            if (
                SilentRepository.APP_EXCLUDED_FROM_VPN &&
                WdttTunnelManager.tunnelReady.value
            ) {
                if (repo.withTunnelApiWhenExcluded { tryFetchProfileOnBase(repo.tunnelApiBaseUrl()) }) {
                    return true
                }
            } else {
                for (base in repo.apiBaseCandidates(null)) {
                    if (tryFetchProfileOnBase(base)) return true
                }
            }
            return _profile.value != null
        }
        if (
            SilentVpnService.isRunning &&
            WdttTunnelManager.tunnelReady.value &&
            bootstrapVpnMode
        ) {
            repo.useApiBase(WdttTunnelManager.tunnelApiBase())
            return tryFetchProfileOnBase(WdttTunnelManager.tunnelApiBase()) || _profile.value != null
        }
        val wg = WdttTunnelManager.lastWgAddress()
        for (base in repo.apiBaseCandidates(wg)) {
            if (tryFetchProfileOnBase(base)) return true
        }
        return _profile.value != null
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
            runCatching {
                val res = if (SilentVpnService.isRunning && !bootstrapVpnMode) {
                    repo.withTunnelApiWhenExcluded { repo.getApi().getTheme() }
                } else {
                    repo.getApi().getTheme()
                }
                if (res.isSuccessful) _theme.value = res.body()
            }
        }
    }

    fun handleDeepLink(uri: Uri?, context: Context? = null) {
        if (uri?.scheme != "silentvpn") return
        when (uri.host) {
            "reset-password" -> uri.getQueryParameter("token")?.takeIf { it.isNotBlank() }?.let { token ->
                _resetPasswordToken.value = token
                _screen.value = AppScreen.LOGIN
                context?.let { ensureBootstrapForAuthFlow(it) }
            }
        }
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
                // Таймер не перезапускаем — те же 2 мин с шага 1.
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка отправки"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
            }
        }
    }

    fun resetPassword(token: String, newPassword: String) {
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
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
            }
        }
    }

    fun login(email: String, password: String, rememberMe: Boolean, activity: ComponentActivity? = null) {
        viewModelScope.launch {
            cancelBootstrapSessionTimeout()
            _authLoading.value = true
            _authError.value = null
            _resetPasswordSuccess.value = false
            try {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _authError.value = "Сначала дождитесь зелёной надписи «Канал готов»"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                if (!WdttTunnelManager.isInternetReady()) {
                    _authError.value = "VPN ещё не готов. Подождите или нажмите «Подключить» снова"
                    restartBootstrapTimerIfNeeded()
                    return@launch
                }
                awaitTunnelApiReady()
                val ctx = activity?.applicationContext ?: appContext
                var loginSucceeded = false
                var offerSavePassword = false
                withBootstrapBackendApi {
                    val res = loginAttempt(email, password)
                    if (!res.isSuccessful) {
                        _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Неверный логин или пароль"
                        restartBootstrapTimerIfNeeded()
                    } else {
                        val tokens = res.body()!!
                        repo.saveTokens(tokens.access_token, tokens.refresh_token)
                        repo.saveRememberMe(email, rememberMe)
                        repo.startNewSession()
                        if (!openLoginSession()) {
                            if (repo.isLoggedIn()) {
                                syncLoginDataViaBootstrapTunnel()
                                loginSucceeded = true
                            }
                        } else {
                            if (!syncLoginDataViaBootstrapTunnel()) {
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
            }
        }
    }

    private suspend fun loginAttempt(email: String, password: String): retrofit2.Response<com.silent.vpn.data.TokenResponse> {
        val bases = preLoginApiBases()
        var lastError: Exception? = null
        for (base in bases) {
            try {
                repo.useApiBase(base)
                DebugLog.i("MainViewModel", "login try API base=$base")
                val res = repo.getApi().login(LoginRequest(email, password))
                DebugLog.i("MainViewModel", "login HTTP ${res.code()} on $base")
                if (res.isSuccessful || res.code() in 400..499) return res
                lastError = Exception(parseError(res.errorBody()?.string() ?: "") ?: "HTTP ${res.code()}")
            } catch (e: Exception) {
                lastError = e
                DebugLog.w("MainViewModel", "login failed on $base: ${e.message}")
            }
        }
        throw lastError ?: Exception("Не удалось связаться с сервером. Проверьте VPN и попробуйте снова.")
    }

    private suspend fun awaitTunnelApiReady() {
        repeat(25) {
            val wg = WdttTunnelManager.lastWgAddress()
            if (!wg.isNullOrBlank()) {
                onVpnTunnelReady()
                return
            }
            delay(200)
        }
        onVpnTunnelReady()
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
                    }
                }
                // Таймер не перезапускаем — те же 2 мин с шага 1, потом VPN отключится.
            } catch (e: Exception) {
                _authError.value = e.message ?: "Ошибка регистрации"
                restartBootstrapTimerIfNeeded()
            } finally {
                _authLoading.value = false
            }
        }
    }

    private suspend fun registerAttempt(email: String, password: String): retrofit2.Response<Map<String, String>> {
        val bases = preLoginApiBases()
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
        WdttTunnelManager.prepareForShutdown()
        stopVpnLocally(context)
        WdttTunnelManager.stopAndAwait()
        SilentRepository.APP_EXCLUDED_FROM_VPN = true
        bootstrapVpnMode = false
        bootstrapContext = null
        _vpnState.value = VpnState.DISCONNECTED
        repo.clearTunnelApiBase()
        _statusMsg.value = "Интернет отключён. VPN включайте на главном экране."
    }

    private fun startBootstrapSessionTimeout(context: Context) {
        cancelBootstrapSessionTimeout()
        bootstrapContext = context.applicationContext
        bootstrapTimeoutJob = viewModelScope.launch {
            val deadline = System.currentTimeMillis() + BOOTSTRAP_SESSION_MS
            while (bootstrapVpnMode && !repo.isLoggedIn()) {
                val leftSec = ((deadline - System.currentTimeMillis()) / 1000L).toInt()
                if (leftSec <= 0) break
                val mm = leftSec / 60
                val ss = leftSec % 60
                _statusMsg.value = when {
                    _resetPasswordToken.value != null ->
                        "Смена пароля через VPN. Осталось %d:%02d".format(mm, ss)
                    _regDone.value ->
                        "Подтвердите email в браузере. VPN ещё %d:%02d".format(mm, ss)
                    _forgotSent.value ->
                        "Откройте ссылку из письма в браузере. VPN ещё %d:%02d".format(mm, ss)
                    else ->
                        "Канал готов. Осталось %d:%02d — войдите или зарегистрируйтесь".format(mm, ss)
                }
                delay(1000)
            }
            if (bootstrapVpnMode && !repo.isLoggedIn()) {
                expireBootstrapSession()
            }
        }
    }

    private fun cancelBootstrapSessionTimeout() {
        bootstrapTimeoutJob?.cancel()
        bootstrapTimeoutJob = null
    }

    private fun expireBootstrapSession() {
        val ctx = bootstrapContext ?: return
        if (!bootstrapVpnMode || repo.isLoggedIn()) return
        DebugLog.i("MainViewModel", "bootstrap session expired (${BOOTSTRAP_SESSION_MS / 1000}s)")
        cancelBootstrapSessionTimeout()
        stopVpnLocally(ctx)
        bootstrapVpnMode = false
        bootstrapContext = null
        _vpnState.value = VpnState.DISCONNECTED
        _statusMsg.value =
            "Время временного интернета истекло (2 мин). Нажмите «Подключить для входа» снова."
    }

    /** Bootstrap VPN on login screen — reach backend through user's VK hash. */
    fun ensureBootstrapVpn(context: Context) {
        if (repo.isLoggedIn() || !isHashReady()) return
        if (bootstrapConnectingInternal) return
        if (bootstrapVpnMode && _vpnState.value == VpnState.CONNECTED) {
            bootstrapContext = context.applicationContext
            startBootstrapSessionTimeout(context)
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
                var config = runCatching {
                    val res = repo.getApi().bootstrapConfig(BootstrapConfigRequest(boot, "android", fp))
                    if (res.isSuccessful) bootstrapLaunchConfig(res.body()!!) else null
                }.getOrNull()

                if (config == null || config.vk_hashes.isEmpty()) {
                    DebugLog.w("MainViewModel", "bootstrap-config недоступен, локальный конфиг через VK TURN")
                    config = bootstrapLaunchConfig(BootstrapVpnConfig.build(boot, fp))
                }

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
                }
                ContextCompat.startForegroundService(context, intent)
                repeat(90) {
                    delay(1000)
                    if (_vpnState.value != VpnState.CONNECTING) return@launch
                    if (WdttTunnelManager.isInternetReady()) {
                        _vpnState.value = VpnState.CONNECTED
                        onVpnTunnelReady(config)
                        startBootstrapSessionTimeout(context)
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
        val ctx = bootstrapContext ?: return
        if (bootstrapVpnMode && !repo.isLoggedIn() && _vpnState.value == VpnState.CONNECTED) {
            startBootstrapSessionTimeout(ctx)
        }
    }

    private suspend fun openLoginSession(): Boolean {
        val boot = repo.getBootstrapHash()
        val res = repo.getApi().registerDevice(
            DeviceRegisterRequest("Android", "android", repo.getDeviceFingerprint(), null, boot)
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
            _theme.value = null
            _vpnState.value = VpnState.DISCONNECTED
            _screen.value = AppScreen.LOGIN
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
        mainTunnelDataSyncJob?.cancel()
        mainTunnelDataSyncJob = null
        backendSyncJob?.cancel()
        backendSyncJob = null
        onlineHeartbeatJob?.cancel()
        onlineHeartbeatJob = null
        runCatching {
            val intent = Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            }
            context.startService(intent)
        }
        WdttTunnelManager.stop()
        repo.clearTunnelApiBase()
    }

    fun connect(context: Context) {
        if (_vpnState.value == VpnState.CONNECTING || _vpnState.value == VpnState.CONNECTED) {
            DebugLog.i("MainViewModel", "connect ignored: ${_vpnState.value}")
            return
        }
        connectJob?.cancel()
        connectJob = viewModelScope.launch {
            DebugLog.i("MainViewModel", "connect() start")
            if (repo.isLoggedIn()) bootstrapVpnMode = false
            if (VpnNetworkHelper.isOtherVpnActive(context)) {
                DebugLog.i("MainViewModel", "Подключение заменит другой активный VPN")
            }
            _vpnState.value = VpnState.CONNECTING
            _vpnError.value = null
            try {
            runCatching {
                refreshProfileForConnect()
                if (!hasVpnAccess()) {
                    _vpnError.value = subscriptionRequiredMessage()
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                val fp = repo.getDeviceFingerprint()
                val cached = loadCachedVpnConfig()
                if (cached != null && isConfigConnectable(cached)) {
                    val connectRes = runCatching { repo.getApi().connect(ConnectRequest(fp, "android")) }.getOrNull()
                    if (connectRes != null && connectRes.code() == 402) {
                        _vpnError.value = parseError(connectRes.errorBody()?.string() ?: "")
                            ?: subscriptionRequiredMessage()
                        _vpnState.value = VpnState.DISCONNECTED
                        loadProfile()
                        return@launch
                    }
                    val config = wdttConnectConfig(resolveMainVpnConfig(cached))
                    DebugLog.i(
                        "MainViewModel",
                        "connect device=${config.device_id.take(12)} n=${config.stream_count} vk=${config.vk_hashes.size}",
                    )
                    launchVpnService(context, config)
                    viewModelScope.launch { refreshVpnConfigInBackground(fp) }
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
                                DeviceRegisterRequest("Android", "android", fp, null, repo.getBootstrapHash())
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
                        vpnConfig!!.vk_hashes.isEmpty() -> "Нет VK-хеша. Введите хеш на экране входа."
                        else -> "Нет ключей WireGuard на сервере. Перезайдите в аккаунт."
                    }
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                val config = wdttConnectConfig(resolveMainVpnConfig(vpnConfig!!))
                DebugLog.i(
                    "MainViewModel",
                    "connect device=${config.device_id.take(12)} n=${config.stream_count} vk=${config.vk_hashes.size}",
                )
                launchVpnService(context, config)
                viewModelScope.launch { refreshVpnConfigInBackground(fp) }
                waitForTunnelReady(context, config.stream_count)
            }.onFailure {
                DebugLog.e("MainViewModel", "connect failed", it)
                _vpnError.value = it.message ?: "Ошибка подключения"
                _vpnState.value = VpnState.DISCONNECTED
            }
            } catch (e: CancellationException) {
                DebugLog.w("MainViewModel", "connect cancelled")
                if (_vpnState.value == VpnState.CONNECTING) {
                    stopVpnLocally(context)
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
        config.vk_hashes.isNotEmpty() &&
            config.wg_private_key.isNotBlank() &&
            config.server_public_key.isNotBlank()

    private fun vpnConfigForWdtt(config: VpnConfig): VpnConfig {
        val boot = repo.getBootstrapHash()?.trim().orEmpty()
        val server = config.vk_hashes
            .filter { it.isNotBlank() && it != boot }
            .distinct()
            .take(HashChannelHelper.MAX_HASHES)
        return if (server.isNotEmpty()) config.copy(vk_hashes = server) else config
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
        return filtered.copy(
            vk_hashes = hashes.ifEmpty { filtered.vk_hashes },
            stream_count = workers,
        )
    }

    private fun launchVpnService(context: Context, config: VpnConfig) {
        val forService = if (bootstrapVpnMode) config else resolveMainVpnConfig(config)
        val wdttConfig = wdttConnectConfig(forService)
        val intent = Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(wdttConfig))
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
            repo.withTunnelApiWhenExcluded {
                val regRes = repo.getApi().registerDevice(
                    DeviceRegisterRequest("Android", "android", fp, null, repo.getBootstrapHash())
                )
                if (regRes.isSuccessful) {
                    var cfg = regRes.body()!!
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
                    runCatching { repo.getApi().connect(ConnectRequest(fp, "android")) }
                }
            }
        }
    }

    /** Таймаут набора групп: 60 с + ~25 с на каждую доп. группу (каскад + капча), макс. 3 мин. */
    private fun connectWaitTimeoutMs(totalWorkers: Int): Int {
        val groups = HashChannelHelper.groupsForWorkers(totalWorkers)
        return (60_000 + (groups - 1).coerceAtLeast(0) * 25_000).coerceAtMost(180_000)
    }

    private fun vpnTunnelUsable(): Boolean =
        WdttTunnelManager.tunnelReady.value && WdttTunnelManager.activeWorkers.value >= 1

    private suspend fun waitForTunnelReady(context: Context, totalWorkers: Int) {
        val timeoutMs = connectWaitTimeoutMs(totalWorkers)
        val iterations = timeoutMs / 100
        repeat(iterations) {
            delay(100)
            if (_vpnState.value != VpnState.CONNECTING) return
            if (WdttTunnelManager.isInternetReady() || vpnTunnelUsable()) {
                if (_vpnState.value == VpnState.CONNECTING) {
                    _vpnState.value = VpnState.CONNECTED
                    onVpnTunnelReady()
                }
                return
            }
        }
        if (_vpnState.value != VpnState.CONNECTING) return
        if (vpnTunnelUsable()) {
            DebugLog.w(
                "MainViewModel",
                "connect wait ended but tunnel OK (${WdttTunnelManager.activeWorkers.value} workers)",
            )
            _vpnState.value = VpnState.CONNECTED
            onVpnTunnelReady()
            return
        }
        val err = WdttTunnelManager.lastError.value
            ?: if (WdttTunnelManager.activeWorkers.value > 0) {
                "WireGuard не поднялся"
            } else {
                WdttTunnelManager.stats.value.takeIf { it.isNotBlank() }
                    ?: "Таймаут: WDTT не подключился к серверу"
            }
        stopVpnLocally(context)
        _vpnError.value = err
        DebugLog.e("MainViewModel", "connect timeout: $err")
        _vpnState.value = VpnState.DISCONNECTED
    }

    fun disconnect(context: Context) {
        connectJob?.cancel()
        connectJob = null
        onlineHeartbeatJob?.cancel()
        onlineHeartbeatJob = null
        vpnProfilePollJob?.cancel()
        vpnProfilePollJob = null
        stopUpdatePolling(clearBanner = true)
        mainTunnelDataSyncJob?.cancel()
        mainTunnelDataSyncJob = null
        backendSyncJob?.cancel()
        backendSyncJob = null
        viewModelScope.launch {
            _vpnState.value = VpnState.DISCONNECTING
            WdttTunnelManager.prepareForShutdown()
            runCatching {
                if (SilentVpnService.isRunning && WdttTunnelManager.tunnelReady.value) {
                    repo.withTunnelApiWhenExcluded {
                        repo.getApi().disconnect(DisconnectRequest(repo.getDeviceFingerprint()))
                    }
                }
            }
            bootstrapVpnMode = false
            stopVpnLocally(context)
            WdttTunnelManager.stopAndAwait()
            repo.clearTunnelApiBase()
            _vpnState.value = VpnState.DISCONNECTED
        }
    }

    fun checkPromo(code: String, onResult: (String) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.withTunnelApiWhenExcluded {
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
                val res = repo.withTunnelApiWhenExcluded {
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
                val res = repo.withTunnelApiWhenExcluded {
                    repo.getApi().initPayment(com.silent.vpn.data.PaymentInitRequest(planType))
                }
                if (res.isSuccessful) onUrl(res.body()!!.url)
                else onError(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка оплаты")
            }.onFailure {
                onError(it.message ?: "Ошибка")
            }
        }
    }

    private suspend fun refreshProfileForConnect() {
        runCatching {
            val res = if (repo.needsTunnelApiOverlay()) {
                repo.withTunnelApiWhenExcluded { repo.getApi().getProfile() }
            } else {
                repo.getApi().getProfile()
            }
            if (res.isSuccessful) _profile.value = res.body()
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
