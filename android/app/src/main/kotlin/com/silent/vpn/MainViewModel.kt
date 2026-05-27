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
import com.silent.vpn.data.ConnectRequest
import com.silent.vpn.data.DeviceRegisterRequest
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.LoginRequest
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
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import javax.inject.Inject

enum class AppScreen { LOGIN, MAIN }

@HiltViewModel
class MainViewModel @Inject constructor(
    private val repo: SilentRepository,
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

    val lastEmail: String get() = repo.getLastEmail().orEmpty()
    val repository: SilentRepository get() = repo

    private fun isHashReady(): Boolean = !repo.getBootstrapHash().isNullOrBlank()

    private fun refreshHashState() {
        _bootstrapHash.value = repo.getBootstrapHash()
        _hashReady.value = isHashReady()
    }

    /** Сохранить хеш из поля и подключить bootstrap VPN. */
    fun connectForLogin(context: Context, raw: String) {
        val h = HashParser.extract(raw)
        if (h == null) {
            _statusMsg.value = "Неверный хеш. Вставьте ссылку vk.com/call/join/… или сам хеш"
            return
        }
        repo.saveBootstrapHash(h)
        refreshHashState()
        ensureBootstrapVpn(context)
    }

    init {
        if (repo.isLoggedIn()) {
            if (!repo.hasSessionFingerprint()) {
                repo.clearTokens()
                _screen.value = AppScreen.LOGIN
            } else {
                refreshSession()
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.lastError.collect { err ->
                if (!err.isNullOrBlank()) {
                    DebugLog.e("MainViewModel", "WDTT error: $err")
                    _vpnError.value = err
                    _vpnState.value = VpnState.DISCONNECTED
                }
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.tunnelReady.collect { ready ->
                if (ready) {
                    DebugLog.i("MainViewModel", "tunnel ready")
                    _vpnState.value = VpnState.CONNECTED
                    markDeviceOnlineOnServer()
                } else if (
                    _vpnState.value == VpnState.CONNECTED &&
                    !WdttTunnelManager.running.value
                ) {
                    _vpnState.value = VpnState.DISCONNECTED
                }
            }
        }
    }

    private fun refreshSession() {
        loadProfile()
        loadTheme()
    }

    private fun markDeviceOnlineOnServer() {
        viewModelScope.launch {
            runCatching {
                repo.getApi().connect(ConnectRequest(repo.getDeviceFingerprint(), "android"))
            }
            loadProfile()
        }
    }

    private fun loadProfile() {
        viewModelScope.launch {
            runCatching {
                val res = repo.getApi().getProfile()
                if (res.isSuccessful) {
                    val p = res.body()!!
                    _profile.value = p
                    p.vk_user_id?.let { repo.saveVkUserId(it) }
                } else if (res.code() == 401) logout()
            }
        }
    }

    private fun loadTheme() {
        viewModelScope.launch {
            runCatching {
                val res = repo.getApi().getTheme()
                if (res.isSuccessful) _theme.value = res.body()
            }
        }
    }

    fun login(email: String, password: String, activity: ComponentActivity? = null) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            runCatching {
                if (_vpnState.value != VpnState.CONNECTED) {
                    _authError.value = "Сначала нажмите «Подключить для входа»"
                    return@launch
                }
                val res = repo.getApi().login(LoginRequest(email, password))
                if (!res.isSuccessful) {
                    _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Неверный логин или пароль"
                    return@launch
                }
                val tokens = res.body()!!
                repo.saveTokens(tokens.access_token, tokens.refresh_token)
                repo.saveLastEmail(email)
                repo.startNewSession()
                if (!openLoginSession()) return@launch
                activity?.let { disconnectBootstrapVpn(it) }
                activity?.let { CredentialHelper.offerSavePassword(it, email, password) }
                refreshSession()
                goToMain()
            }.onFailure {
                _authError.value = it.message ?: "Ошибка входа"
            }
            _authLoading.value = false
        }
    }

    fun register(email: String, password: String) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            runCatching {
                val res = repo.getApi().register(RegisterRequest(email, password))
                if (!res.isSuccessful) {
                    _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Ошибка регистрации"
                    return@launch
                }
                _regEmail.value = email
                _regDone.value = true
            }.onFailure {
                _authError.value = it.message ?: "Ошибка регистрации"
            }
            _authLoading.value = false
        }
    }

    fun clearAuthError() { _authError.value = null }
    fun clearVpnError() { _vpnError.value = null }
    fun showError(msg: String) { _vpnError.value = msg }
    fun dismissRegDone() { _regDone.value = false; _regEmail.value = "" }

    fun goToMain() {
        _screen.value = AppScreen.MAIN
    }

    private fun disconnectBootstrapVpn(context: Context) {
        if (!bootstrapVpnMode) return
        stopVpnLocally(context)
        bootstrapVpnMode = false
        _vpnState.value = VpnState.DISCONNECTED
        _statusMsg.value = "Интернет отключён. VPN включайте на главном экране."
    }

    /** Bootstrap VPN on login screen — reach backend through user's VK hash. */
    fun ensureBootstrapVpn(context: Context) {
        if (repo.isLoggedIn() || !isHashReady()) return
        if (_vpnState.value == VpnState.CONNECTED || bootstrapConnectingInternal) return
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
                val res = repo.getApi().bootstrapConfig(
                    BootstrapConfigRequest(boot, "android", fp)
                )
                if (!res.isSuccessful) {
                    Log.w("MainViewModel", "bootstrap-config ${res.code()}")
                    DebugLog.w("MainViewModel", "bootstrap-config HTTP ${res.code()}: ${res.errorBody()?.string()?.take(200)}")
                    _statusMsg.value = parseError(res.errorBody()?.string() ?: "")
                        ?: "Не удалось получить bootstrap-конфиг"
                    return@launch
                }
                var config = applyBootstrapHash(res.body()!!)
                if (config.vk_hashes.isEmpty() || config.wg_private_key.isBlank()) {
                    _statusMsg.value = "Bootstrap-конфиг неполный"
                    return@launch
                }
                bootstrapVpnMode = true
                _vpnState.value = VpnState.CONNECTING
                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_CONNECT
                    putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(config))
                }
                ContextCompat.startForegroundService(context, intent)
                repeat(90) {
                    delay(1000)
                    if (_vpnState.value != VpnState.CONNECTING) return@launch
                    if (WdttTunnelManager.tunnelReady.value) {
                        _vpnState.value = VpnState.CONNECTED
                        _statusMsg.value = "Канал готов. Можно войти или зарегистрироваться."
                        return@launch
                    }
                }
                if (_vpnState.value == VpnState.CONNECTING) {
                    stopVpnLocally(context)
                    bootstrapVpnMode = false
                    _vpnState.value = VpnState.DISCONNECTED
                    _statusMsg.value = WdttTunnelManager.lastError.value ?: "Таймаут bootstrap VPN"
                }
            } catch (e: Exception) {
                Log.e("MainViewModel", "bootstrap VPN", e)
                _statusMsg.value = e.message ?: "Ошибка bootstrap VPN"
            } finally {
                bootstrapConnectingInternal = false
                _bootstrapConnecting.value = false
            }
        }
    }

    private suspend fun openLoginSession(): Boolean {
        val boot = repo.getBootstrapHash()
        val res = repo.getApi().registerDevice(
            DeviceRegisterRequest("Android", "android", repo.getDeviceFingerprint(), null, boot)
        )
        if (res.isSuccessful) {
            val cfg = res.body()!!
            repo.saveSessionDeviceId(cfg.device_id)
            repo.cacheVpnConfig(Gson().toJson(cfg))
            _sessionDeviceId.value = cfg.device_id
            return true
        }
        _authError.value = parseError(res.errorBody()?.string() ?: "")
            ?: "Достигнут лимит устройств (3). Выйдите на другом устройстве."
        repo.clearSessionFingerprint()
        repo.clearTokens()
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

            if (fp != null && repo.getAccessToken() != null) {
                runCatching {
                    val res = repo.getApi().logoutSession(DisconnectRequest(fp))
                    if (!res.isSuccessful) {
                        Log.w("MainViewModel", "logout API ${res.code()}")
                    }
                }
            }

            repo.clearSessionFingerprint()
            repo.clearSessionDeviceId()
            repo.clearCachedVpnConfig()
            repo.clearTokens()
            _sessionDeviceId.value = null
            _profile.value = null
            _theme.value = null
            _vpnState.value = VpnState.DISCONNECTED
            _screen.value = AppScreen.LOGIN
            _authError.value = null
            _vpnError.value = null
            _regDone.value = false
        }
    }

    private fun stopVpnLocally(context: Context) {
        runCatching {
            val intent = Intent(context, SilentVpnService::class.java).apply {
                action = SilentVpnService.ACTION_DISCONNECT
            }
            context.startService(intent)
        }
        WdttTunnelManager.stop()
    }

    fun connect(context: Context) {
        viewModelScope.launch {
            DebugLog.i("MainViewModel", "connect() start")
            _vpnState.value = VpnState.CONNECTING
            _vpnError.value = null
            runCatching {
                val fp = repo.getDeviceFingerprint()
                val cached = loadCachedVpnConfig()
                if (cached != null && isConfigConnectable(cached)) {
                    DebugLog.i("MainViewModel", "fast connect from cache")
                    runCatching { repo.getApi().connect(ConnectRequest(fp, "android")) }
                    launchVpnService(context, cached)
                    viewModelScope.launch { refreshVpnConfigInBackground(fp) }
                    waitForTunnelReady(context)
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
                            403 -> {
                                _vpnError.value = parseError(regRes.errorBody()?.string() ?: "") ?: "Доступ запрещён"
                                _vpnState.value = VpnState.DISCONNECTED
                                accessDenied = true
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
                            }
                        }
                    }

                    if (vpnConfig == null) {
                        vpnConfig = loadCachedVpnConfig()
                    }

                    vpnConfig = vpnConfig?.let { applyBootstrapHash(it) }

                    hashesJob.await()?.let { hres ->
                        if (hres.isSuccessful) {
                            val all = hres.body()?.hashes?.filter { it.isNotBlank() }
                            if (!all.isNullOrEmpty() && vpnConfig != null) {
                                vpnConfig = vpnConfig!!.copy(vk_hashes = all)
                                repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                                if (all.size <= 1) {
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

                runCatching { repo.getApi().connect(ConnectRequest(fp, "android")) }
                launchVpnService(context, vpnConfig!!)
                loadProfile()
                waitForTunnelReady(context)
            }.onFailure {
                DebugLog.e("MainViewModel", "connect failed", it)
                _vpnError.value = it.message ?: "Ошибка подключения"
                _vpnState.value = VpnState.DISCONNECTED
            }
        }
    }

    private fun loadCachedVpnConfig(): VpnConfig? {
        val cached = repo.getCachedVpnConfig() ?: return null
        val parsed = runCatching { Gson().fromJson(cached, VpnConfig::class.java) }.getOrNull() ?: return null
        if (parsed.device_id != repo.getSessionDeviceId()) return null
        return applyBootstrapHash(parsed)
    }

    private fun isConfigConnectable(config: VpnConfig): Boolean =
        config.vk_hashes.isNotEmpty() &&
            config.wg_private_key.isNotBlank() &&
            config.server_public_key.isNotBlank()

    private fun launchVpnService(context: Context, config: VpnConfig) {
        val intent = Intent(context, SilentVpnService::class.java).apply {
            action = SilentVpnService.ACTION_CONNECT
            putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(config))
        }
        ContextCompat.startForegroundService(context, intent)
    }

    private suspend fun refreshVpnConfigInBackground(fp: String) {
        runCatching {
            val regRes = repo.getApi().registerDevice(
                DeviceRegisterRequest("Android", "android", fp, null, repo.getBootstrapHash())
            )
            if (regRes.isSuccessful) {
                var cfg = applyBootstrapHash(regRes.body()!!)
                repo.saveSessionDeviceId(cfg.device_id)
                _sessionDeviceId.value = cfg.device_id
                val hres = repo.getApi().getVpnHashes()
                if (hres.isSuccessful) {
                    val all = hres.body()?.hashes?.filter { it.isNotBlank() }
                    if (!all.isNullOrEmpty()) cfg = cfg.copy(vk_hashes = all)
                }
                repo.cacheVpnConfig(Gson().toJson(cfg))
                runCatching { repo.getApi().connect(ConnectRequest(fp, "android")) }
            }
        }
    }

    private suspend fun waitForTunnelReady(context: Context) {
        repeat(150) {
            delay(200)
            if (_vpnState.value != VpnState.CONNECTING) return
            if (WdttTunnelManager.tunnelReady.value) return
        }
        if (_vpnState.value == VpnState.CONNECTING) {
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
    }

    fun disconnect(context: Context) {
        viewModelScope.launch {
            _vpnState.value = VpnState.DISCONNECTING
            runCatching {
                repo.getApi().disconnect(DisconnectRequest(repo.getDeviceFingerprint()))
                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_DISCONNECT
                }
                context.startService(intent)
            }
            WdttTunnelManager.stop()
            _vpnState.value = VpnState.DISCONNECTED
            loadProfile()
        }
    }

    fun checkPromo(code: String, onResult: (String) -> Unit) {
        viewModelScope.launch {
            runCatching {
                val res = repo.getApi().checkPromo(PromoCheckRequest(code, "monthly"))
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
                val res = repo.getApi().renameDevice(deviceId, com.silent.vpn.data.DeviceRenameRequest(name))
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
                val res = repo.getApi().initPayment(com.silent.vpn.data.PaymentInitRequest(planType))
                if (res.isSuccessful) onUrl(res.body()!!.url)
                else onError(parseError(res.errorBody()?.string() ?: "") ?: "Ошибка оплаты")
            }.onFailure {
                onError(it.message ?: "Ошибка")
            }
        }
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
