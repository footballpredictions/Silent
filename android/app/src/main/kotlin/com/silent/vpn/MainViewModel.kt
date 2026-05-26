package com.silent.vpn

import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.silent.vpn.data.ConnectRequest
import com.silent.vpn.data.DeviceRegisterRequest
import com.silent.vpn.data.DisconnectRequest
import com.silent.vpn.data.LoginRequest
import com.silent.vpn.data.PromoCheckRequest
import com.silent.vpn.data.RegisterRequest
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.data.ThemeData
import com.silent.vpn.data.UserProfile
import com.silent.vpn.data.VkAttachRequest
import com.silent.vpn.data.VpnConfig
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.ui.screens.VpnState
import com.silent.vpn.vk.VkConfigFetcher
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
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

    private val _vkUserId = MutableStateFlow(repo.getVkUserId().takeIf { it > 0 })
    val vkUserId: StateFlow<Long?> = _vkUserId

    private val _vkReady = MutableStateFlow(isVkReady())
    val vkReady: StateFlow<Boolean> = _vkReady

    private val _vkMsg = MutableStateFlow("")
    val vkMsg: StateFlow<String> = _vkMsg

    private fun isVkReady(): Boolean =
        repo.getVkUserId() > 0 && !repo.getBootstrapHash().isNullOrBlank()

    private fun refreshVkState() {
        _vkUserId.value = repo.getVkUserId().takeIf { it > 0 }
        _bootstrapHash.value = repo.getBootstrapHash()
        _vkReady.value = isVkReady()
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
                    _vpnError.value = err
                    _vpnState.value = VpnState.DISCONNECTED
                }
            }
        }
        viewModelScope.launch {
            WdttTunnelManager.tunnelReady.collect { ready ->
                if (ready) {
                    _vpnState.value = VpnState.CONNECTED
                } else if (_vpnState.value == VpnState.CONNECTED) {
                    _vpnState.value = VpnState.DISCONNECTED
                }
            }
        }
    }

    private fun refreshSession() {
        loadProfile()
        loadTheme()
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

    fun login(email: String, password: String) {
        viewModelScope.launch {
            _authLoading.value = true
            _authError.value = null
            runCatching {
                val res = repo.getApi().login(LoginRequest(email, password))
                if (!res.isSuccessful) {
                    _authError.value = parseError(res.errorBody()?.string() ?: "") ?: "Неверный логин или пароль"
                    return@launch
                }
                val tokens = res.body()!!
                repo.saveTokens(tokens.access_token, tokens.refresh_token)
                val localVkId = repo.getVkUserId().takeIf { it > 0 }
                if (localVkId != null) {
                    runCatching {
                        val att = repo.getApi().vkLinkAttach(VkAttachRequest(localVkId))
                        if (att.isSuccessful) {
                            att.body()?.bootstrap_hash?.let { repo.saveBootstrapHash(it) }
                            refreshVkState()
                        } else {
                            _vkMsg.value = parseError(att.errorBody()?.string() ?: "")
                                ?: "Не удалось привязать VK к аккаунту"
                        }
                    }.onFailure {
                        _vkMsg.value = it.message ?: "Ошибка привязки VK"
                    }
                }
                repo.startNewSession()
                if (!openLoginSession()) return@launch
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

    fun clearVkMsg() { _vkMsg.value = "" }

    private fun refreshBootstrapHash() {
        refreshVkState()
    }

    private suspend fun openLoginSession(): Boolean {
        val res = repo.getApi().registerDevice(
            DeviceRegisterRequest("Android", "android", repo.getDeviceFingerprint(), null)
        )
        if (res.isSuccessful) return true
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
            repo.clearTokens()
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
            _vpnState.value = VpnState.CONNECTING
            _vpnError.value = null
            runCatching {
                val fp = repo.getDeviceFingerprint()
                var vpnConfig: VpnConfig? = null
                var apiError: String? = null

                runCatching {
                    val regRes = repo.getApi().registerDevice(
                        DeviceRegisterRequest("Android", "android", fp, null)
                    )
                    when (regRes.code()) {
                        402 -> {
                            _vpnError.value = "Нет активной подписки"
                            _vpnState.value = VpnState.DISCONNECTED
                            return@launch
                        }
                        403 -> {
                            _vpnError.value = parseError(regRes.errorBody()?.string() ?: "") ?: "Доступ запрещён"
                            _vpnState.value = VpnState.DISCONNECTED
                            return@launch
                        }
                    }
                    if (regRes.isSuccessful) {
                        vpnConfig = regRes.body()!!
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
                    runCatching {
                        val vkRes = repo.getApi().vkConfigSync()
                        if (vkRes.isSuccessful) {
                            vpnConfig = vkRes.body()!!
                            repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                        }
                    }
                }

                if (vpnConfig == null) {
                    val vkUserId = _profile.value?.vk_user_id ?: repo.getVkUserId().takeIf { it > 0 }
                    if (vkUserId != null && vkUserId > 0) {
                        vpnConfig = VkConfigFetcher.fetchConfig(vkUserId, repo.getVkAccessToken())
                        if (vpnConfig != null) repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                    }
                }

                if (vpnConfig == null) {
                    repo.getCachedVpnConfig()?.let { cached ->
                        vpnConfig = Gson().fromJson(cached, VpnConfig::class.java)
                    }
                }

                if (vpnConfig == null) {
                    _vpnError.value = apiError ?: "Сервер недоступен. Загрузите конфиг из VK в настройках или подключитесь при доступном интернете."
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                vpnConfig = applyBootstrapHash(vpnConfig!!)

                runCatching {
                    val hres = repo.getApi().getVpnHashes()
                    if (hres.isSuccessful) {
                        val all = hres.body()?.hashes?.filter { it.isNotBlank() }
                        if (!all.isNullOrEmpty()) {
                            vpnConfig = vpnConfig!!.copy(vk_hashes = all)
                            repo.cacheVpnConfig(Gson().toJson(vpnConfig))
                        }
                    }
                }

                if (vpnConfig!!.vk_hashes.isEmpty()) {
                    _vpnError.value = "Нет VK-хеша. Привяжите VK и получите сообщение от бота."
                    _vpnState.value = VpnState.DISCONNECTED
                    return@launch
                }

                runCatching {
                    repo.getApi().connect(ConnectRequest(fp, "android"))
                }

                val intent = Intent(context, SilentVpnService::class.java).apply {
                    action = SilentVpnService.ACTION_CONNECT
                    putExtra(SilentVpnService.EXTRA_CONFIG, Gson().toJson(vpnConfig))
                }
                ContextCompat.startForegroundService(context, intent)
                loadProfile()
            }.onFailure {
                _vpnError.value = it.message ?: "Ошибка подключения"
                _vpnState.value = VpnState.DISCONNECTED
            }
        }
    }

    fun linkVkGuest(onOpenUrl: (String) -> Unit) {
        viewModelScope.launch {
            _vkMsg.value = "Открытие VK..."
            runCatching {
                val res = repo.getApi().vkGuestLinkStart()
                if (!res.isSuccessful) {
                    _vkMsg.value = parseError(res.errorBody()?.string() ?: "") ?: "Не удалось начать привязку VK"
                    return@launch
                }
                val data = res.body()!!
                onOpenUrl(data.auth_url)
                repeat(90) {
                    delay(2000)
                    val st = repo.getApi().vkGuestStatus(data.state)
                    if (st.isSuccessful && st.body()?.completed == true) {
                        val body = st.body()!!
                        body.vk_user_id?.let { repo.saveVkUserId(it) }
                        body.bootstrap_hash?.let { repo.saveBootstrapHash(it) }
                        refreshVkState()
                        _vkMsg.value = "VK готов. Первый хеш получен — войдите в аккаунт."
                        return@launch
                    }
                }
                _vkMsg.value = "Завершите вход VK в браузере или вернитесь в приложение."
            }.onFailure {
                _vkMsg.value = it.message ?: "Ошибка привязки VK"
            }
        }
    }

    /** @deprecated use linkVkGuest */
    fun linkVk(onOpenUrl: (String) -> Unit) = linkVkGuest(onOpenUrl)

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

    fun handleVkDeepLink(bootHash: String?, vkUserId: Long?) {
        viewModelScope.launch {
            bootHash?.takeIf { it.isNotBlank() }?.let { repo.saveBootstrapHash(it) }
            vkUserId?.takeIf { it > 0 }?.let { repo.saveVkUserId(it) }
            refreshVkState()
            if (!bootHash.isNullOrBlank()) {
                _vkMsg.value = "Первый хеш получен. Войдите в аккаунт Silent."
            } else {
                _vkMsg.value = "VK подключён. Войдите в аккаунт Silent."
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
