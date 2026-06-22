package com.silent.vpn.data

import android.content.Context
import android.content.ClipboardManager
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.Network
import android.util.Log
import com.silent.vpn.BuildConfig
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.silent.vpn.vpn.TunnelApiProxy
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.Response
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

@Singleton
class SilentRepository @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        private const val TAG = "SilentRepository"
        const val DEFAULT_SERVER_URL = "https://132.243.234.162"
        const val DEFAULT_SERVER_HOST = "132-243-234-162.nip.io"
        const val PREF_SERVER_URL = "server_url"
        const val PREF_ACCESS_TOKEN = "access_token"
        const val PREF_REFRESH_TOKEN = "refresh_token"
        const val PREF_DEVICE_FP = "device_fingerprint"
        const val PREF_STABLE_FP = "stable_device_fp"
        const val PREF_VK_USER_ID = "vk_user_id"
        const val PREF_VK_ACCESS_TOKEN = "vk_access_token"
        const val PREF_BOOTSTRAP_HASH = "vk_bootstrap_hash"
        const val PREF_PRE_LOGIN_FP = "pre_login_fp"
        const val PREF_CACHED_CONFIG = "cached_vpn_config"
        const val PREF_CACHED_CONFIG_TS = "cached_vpn_config_ts"
        const val PREF_LAST_EMAIL = "last_email"
        const val PREF_REMEMBERED_PASSWORD = "remembered_password"
        const val PREF_REMEMBER_ME = "remember_me"
        const val PREF_SESSION_DEVICE_ID = "session_device_id"
        const val PREF_EXCLUDED_APPS = "excluded_apps"
        const val PREF_EXCLUSIONS_WHITELIST = "exclusions_whitelist"
        const val PREF_SAVED_HASH_ITEMS = "saved_hash_items"
        const val PREF_SAVED_HASH_ITEMS_TS = "saved_hash_items_ts"
        const val PREF_HASH_CHANNELS_PER_HASH = "hash_channels_per_hash"
        const val PREF_HASH_TOTAL_WORKERS = "hash_total_workers"
        const val PREF_HASH_LEGACY_MIGRATED = "hash_total_workers_legacy_migrated"
        const val PREF_CACHED_PROFILE = "cached_profile_json"
        const val PREF_CACHED_THEME = "cached_theme_json"
        const val PREF_SYNC_HASHES_REV = "config_sync_hashes_rev"
        const val PREF_SYNC_THEME_REV = "config_sync_theme_rev"
        const val PREF_SYNC_PROFILE_REV = "config_sync_profile_rev"
        const val PREF_EPHEMERAL_SYNC_LAST_MS = "ephemeral_sync_last_ms"
        /** Минимальный интервал между авто ephemeral bootstrap (кнопка «Обновить» — без лимита). */
        const val EPHEMERAL_SYNC_MIN_MS = 30 * 60 * 1000L
        const val VK_APP_ID = 54610377L
        const val VK_GROUP_ID = 239092728L
        const val WG_TUNNEL_GATEWAY = "10.66.66.1"
        /** false только при apiOverlayMode (краткий overlay для HTTP к 10.66.66.1). */
        var APP_EXCLUDED_FROM_VPN = true

        /** Сериализация config-sync — не параллелить с overlay/connect. */
        private val configSyncMutex = Mutex()
    }

    private val prefs: SharedPreferences = createPrefs(context)

    private var _api: SilentApi? = null
    private var _apiCacheKey: String? = null
    private var _baseUrl: String = ""
    /** Когда VPN поднят — API через адрес в туннеле (10.66.66.1), иначе nip.io недоступен в белых списках. */
    private var tunnelApiBaseUrl: String? = null

    @Volatile private var publicReachableCache: Boolean? = null
    @Volatile private var publicReachableCachedAtMs = 0L
    private val tunnelSyncMutex = Mutex()

    init {
        ensureServerUrl()
    }

    private fun createPrefs(context: Context): SharedPreferences = SilentPrefs.open(context)

    fun getApi(): SilentApi {
        val url = getServerUrl().trimEnd('/')
        val vpnNet = resolveVpnNetworkForApi(url)
        val cacheKey = if (vpnNet != null) "$url|vpn" else url
        if (_api == null || _apiCacheKey != cacheKey) {
            _apiCacheKey = cacheKey
            _baseUrl = "$url/"
            _api = buildApi(_baseUrl, vpnNetwork = vpnNet)
        }
        return _api!!
    }

    /** Excluded app: HTTP к 10.66.66.1 — только через VPN Network (как Chrome в туннеле). */
    private fun resolveVpnNetworkForApi(url: String): Network? {
        if (!APP_EXCLUDED_FROM_VPN || !isMainVpnTunnelUp()) return null
        if (url.startsWith(TunnelApiProxy.baseUrl())) return null
        if (!url.contains(WG_TUNNEL_GATEWAY)) return null
        return VpnNetworkHelper.getSilentVpnNetwork(context)
    }

    private fun buildApi(baseUrl: String, vpnNetwork: Network? = null, connectTimeoutSec: Long? = null): SilentApi {
        val nipHost = DEFAULT_SERVER_HOST
        val builder = OkHttpClient.Builder()
        if (BuildConfig.DEBUG) {
            builder.addInterceptor(
                HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC },
            )
        }
        builder
            .addInterceptor { chain ->
                var req = chain.request()
                val token = getAccessToken()
                if (token != null) {
                    req = req.newBuilder().header("Authorization", "Bearer $token").build()
                }
                // HTTPS по IP: nginx ждёт Host с nip.io
                if (req.url.host.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) {
                    req = req.newBuilder().header("Host", nipHost).build()
                }
                val host = req.url.host
                val viaTunnelGw = host == WG_TUNNEL_GATEWAY || host.startsWith("10.66.")
                if (viaTunnelGw && APP_EXCLUDED_FROM_VPN && isMainVpnTunnelUp()) {
                    val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
                    val network = VpnNetworkHelper.getSilentVpnNetwork(context)
                    if (network != null) {
                        val prev = cm.boundNetworkForProcess
                        if (cm.bindProcessToNetwork(network)) {
                            try {
                                return@addInterceptor chain.proceed(req)
                            } finally {
                                cm.bindProcessToNetwork(prev)
                            }
                        }
                    }
                }
                chain.proceed(req)
            }
            .hostnameVerifier { _, _ -> true }
            .sslSocketFactory(TrustAllCerts.sslSocketFactory(), TrustAllCerts.trustManager())
        vpnNetwork?.let { builder.socketFactory(it.socketFactory) }
        val connectSec = connectTimeoutSec ?: if (baseUrl.contains("10.66.")) 12L else 4L
        builder
            .connectTimeout(connectSec, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
        val client = builder.build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SilentApi::class.java)
    }

    fun getServerUrl(): String {
        tunnelApiBaseUrl?.let { return it }
        if (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value) {
            return tunnelApiBase()
        }
        return getPublicServerUrl().trimEnd('/')
    }

    fun invalidatePublicReachabilityCache() {
        publicReachableCache = null
        publicReachableCachedAtMs = 0L
    }

    /** Public nip.io доступен (Wi‑Fi) — routine API без tunnel/overlay. */
    suspend fun isPublicBackendReachable(forceProbe: Boolean = false): Boolean {
        val now = System.currentTimeMillis()
        if (isOnMobileData()) {
            publicReachableCache = false
            publicReachableCachedAtMs = now
            return false
        }
        if (!forceProbe &&
            publicReachableCache != null &&
            now - publicReachableCachedAtMs < 45_000L
        ) {
            return publicReachableCache!!
        }
        if (!VpnNetworkHelper.hasUnderlyingInternet(context)) {
            publicReachableCache = false
            publicReachableCachedAtMs = now
            return false
        }
        val ok = probePublicBackendReachable()
        publicReachableCache = ok
        publicReachableCachedAtMs = now
        Log.i(TAG, "public backend reachable=$ok")
        return ok
    }

    fun isOnMobileData(): Boolean = VpnNetworkHelper.isOnMobileData(context)

    /** Фоновый ConfigSync без VPN — только Wi‑Fi. */
    fun allowsWifiBackgroundSync(): Boolean = !isOnMobileData()

    /**
     * Канал обновлений: Wi‑Fi всегда; mobile — только при поднятом main VPN (proxy/direct, без overlay).
     */
    fun allowsBackgroundConfigSync(): Boolean =
        !isOnMobileData() || isMainVpnTunnelUp()

    fun mayRunEphemeralSync(force: Boolean = false): Boolean {
        if (force) return true
        val last = prefs.getLong(PREF_EPHEMERAL_SYNC_LAST_MS, 0L)
        return last <= 0L || System.currentTimeMillis() - last >= EPHEMERAL_SYNC_MIN_MS
    }

    fun markEphemeralSyncUsed() {
        prefs.edit().putLong(PREF_EPHEMERAL_SYNC_LAST_MS, System.currentTimeMillis()).apply()
    }

    fun ephemeralSyncCooldownSec(): Int? {
        val last = prefs.getLong(PREF_EPHEMERAL_SYNC_LAST_MS, 0L)
        if (last <= 0L) return null
        val left = EPHEMERAL_SYNC_MIN_MS - (System.currentTimeMillis() - last)
        return if (left > 0L) ((left + 999L) / 1000L).toInt() else null
    }

    /** Public HTTPS недоступен (типично LTE с белыми списками). */
    fun isPublicConnectFailure(message: String?): Boolean {
        val m = message?.lowercase().orEmpty()
        if (m.isBlank()) return false
        return m.contains("failed to connect") ||
            m.contains("connect timed out") ||
            m.contains("timeout") ||
            m.contains("unable to resolve") ||
            m.contains("connection refused") ||
            m.contains("network is unreachable") ||
            m.contains("all api routes failed") ||
            m.contains("no route to host") ||
            m.contains("software caused connection abort") ||
            m.contains("upstream error") ||
            m.contains("upstream failed") ||
            m.contains("vpn upstream") ||
            m.contains("tunnel backend unavailable")
    }

    /** VPN поднят, public недоступен — хеши/сессии только через proxy. */
    fun needsTunnelProxyForBackend(): Boolean =
        isOnMobileData() ||
            (isMainVpnTunnelUp() && publicReachableCache == false)

    private suspend fun probePublicBackendReachable(): Boolean {
        val prev = tunnelApiBaseUrl
        try {
            for (base in publicApiBases()) {
                val hit = runCatching {
                    val api = buildApi("${base.trimEnd('/')}/", connectTimeoutSec = 3L)
                    val res = api.getTheme()
                    res.isSuccessful
                }.getOrDefault(false)
                if (hit) return true
            }
            return false
        } finally {
            tunnelApiBaseUrl = prev
            invalidateApiClient()
        }
    }

    /** ConfigSync, профиль, сессии — Wi‑Fi public; mobile + VPN — tunnel proxy/direct без overlay. */
    suspend fun <T> withRoutineBackendApi(
        allowOverlayFallback: Boolean = false,
        block: suspend () -> T,
    ): T {
        if (isOnMobileData()) {
            if (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value) {
                useApiBase(tunnelApiBase())
                invalidateApiClient()
                return block()
            }
            if (isMainVpnTunnelUp()) {
                return withTunnelBackendBlock(allowOverlayFallback, block)
            }
            useApiBase(getPublicServerUrl())
            invalidateApiClient()
            return block()
        }

        val tunnelUp = isMainVpnTunnelUp()

        if (!tunnelUp || isPublicBackendReachable()) {
            useApiBase(getPublicServerUrl())
            invalidateApiClient()
            return runCatching { block() }.getOrElse { e ->
                if (tunnelUp) {
                    Log.w(TAG, "public API failed on VPN Wi‑Fi: ${e.message}, tunnel fallback")
                    withTunnelBackendBlock(allowOverlayFallback, block)
                } else {
                    throw e
                }
            }
        }

        return withTunnelBackendBlock(allowOverlayFallback, block)
    }

    /** Промокод, подписка, оплата — при сбое direct/proxy краткий overlay (как ephemeral). */
    suspend fun <T> withUserBackendApi(block: suspend () -> T): T =
        withRoutineBackendApi(allowOverlayFallback = true, block = block)

    /** Proxy → direct bind; overlay fallback только для withUserBackendApi. */
    private suspend fun <T> withTunnelBackendBlock(
        allowOverlayFallback: Boolean = false,
        block: suspend () -> T,
    ): T {
        if (!APP_EXCLUDED_FROM_VPN && isMainVpnTunnelUp()) {
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            Log.i(TAG, "tunnel API direct (app in VPN, no overlay)")
            return block()
        }

        var last: Throwable? = null

        if (isMainVpnTunnelUp()) {
            repeat(3) { attempt ->
                useApiBase(tunnelApiBase())
                invalidateApiClient()
                val result = runCatching { block() }
                if (result.isSuccess && !isTunnelBackendFailure(result.getOrNull())) {
                    Log.i(TAG, "tunnel API direct bind OK")
                    return result.getOrThrow()
                }
                last = result.exceptionOrNull()
                if (result.isFailure) {
                    Log.w(TAG, "tunnel direct attempt ${attempt + 1}: ${last?.message}")
                } else {
                    Log.w(TAG, "tunnel direct attempt ${attempt + 1}: bad HTTP via tunnel")
                }
                invalidateApiClient()
                if (attempt < 2) delay(500)
            }
            Log.i(TAG, "tunnel direct failed → proxy ${TunnelApiProxy.baseUrl()}")
        }

        repeat(4) { attempt ->
            if (prepareTunnelApiBase()) {
                val result = runCatching { block() }
                if (result.isSuccess && !isTunnelBackendFailure(result.getOrNull())) {
                    return result.getOrThrow()
                }
                last = result.exceptionOrNull()
                if (result.isFailure) {
                    Log.w(TAG, "tunnel proxy attempt ${attempt + 1}: ${last?.message}")
                } else {
                    Log.w(TAG, "tunnel proxy attempt ${attempt + 1}: upstream failed")
                }
                invalidateApiClient()
            } else {
                Log.w(TAG, "tunnel proxy not ready (attempt ${attempt + 1})")
                if (attempt < 3) ensureTunnelApiProxy()
            }
            if (attempt < 3) delay(750)
        }

        if (allowOverlayFallback && APP_EXCLUDED_FROM_VPN && isMainVpnTunnelUp()) {
            Log.i(TAG, "tunnel API → brief overlay fallback")
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            return com.silent.vpn.vpn.WdttTunnelManager.withApiOverlayBrief(
                block = block,
                allowDuringRampUp = true,
            )
        }
        throw last ?: IllegalStateException("tunnel backend unavailable")
    }

    /** 502/503 от proxy — retry; любой другой HTTP (402, 404…) — канал жив, отдаём вызывающему. */
    private fun isTunnelBackendFailure(value: Any?): Boolean {
        if (value is Response<*>) {
            return value.code() == 502 || value.code() == 503
        }
        return false
    }

    /** Public HTTPS — только fallback (Wi‑Fi); на mobile Chrome идёт через VPN, app excluded. */
    private fun publicApiBases(): List<String> = listOf(
        "https://$DEFAULT_SERVER_HOST",
        getPublicServerUrl().trimEnd('/'),
    ).distinct().filter { it.isNotBlank() }

    private fun tunnelApiBase(): String = "http://$WG_TUNNEL_GATEWAY:8000"

    /** Bootstrap / app в туннеле — API только через 10.66.66.1 (как PC enableTunnelApi). */
    fun ensureBootstrapTunnelApi(): Boolean {
        if (!WdttTunnelManager.isBootstrapMode() || !WdttTunnelManager.tunnelReady.value) return false
        useApiBase(tunnelApiBase())
        invalidateApiClient()
        Log.i(TAG, "API via bootstrap tunnel: ${tunnelApiBase()}")
        return true
    }

    fun setTunnelApiFromWgAddress(wgAddress: String?) {
        if (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value) {
            ensureBootstrapTunnelApi()
            return
        }
        if (isMainVpnTunnelUp() && APP_EXCLUDED_FROM_VPN) {
            useApiBase(tunnelApiBaseUrl())
            invalidateApiClient()
            return
        }
        if (!APP_EXCLUDED_FROM_VPN && WdttTunnelManager.tunnelReady.value) {
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            Log.i(TAG, "API via tunnel (app in VPN): ${tunnelApiBase()}")
            return
        }
        val gw = wgGatewayFromAddress(wgAddress) ?: return
        useApiBase("http://$gw:8000")
        invalidateApiClient()
        Log.i(TAG, "API via tunnel: http://$gw:8000")
    }

    /** Перед connect sync — только сброс клиента. */
    fun prepareTunnelApiFromCachedConfig() {
        invalidateApiClient()
    }

    /** Хеши + VPN-конфиг через тот же канал, что POST /connect (из VpnBackendSync). */
    suspend fun syncHashesAndConfigAfterConnect(): Boolean {
        if (!isLoggedIn()) return false
        val forceTunnel = isMainVpnTunnelUp() && isOnMobileData()
        var hashesOk = false
        if (!forceTunnel && isPublicBackendReachable()) {
            fetchHashItemsFromPublicBases(fastTimeout = false).onSuccess {
                if (it.isNotEmpty()) {
                    hashesOk = true
                    Log.i(TAG, "syncHashes OK public (${it.size} items)")
                }
            }.onFailure { e -> Log.w(TAG, "syncHashes public: ${e.message}") }
        } else {
            runCatching {
                withRoutineBackendApi {
                    val items = fetchHashItemsOnce().getOrThrow()
                    if (items.isNotEmpty()) {
                        hashesOk = true
                        Log.i(TAG, "syncHashes OK tunnel (${items.size} items)")
                    }
                }
            }.onFailure { e -> Log.w(TAG, "syncHashes tunnel: ${e.message}") }
        }
        var configOk = false
        val fp = getDeviceFingerprint()
        runCatching {
            withRoutineBackendApi {
                val res = getApi().getConfig(fp)
                if (res.isSuccessful) {
                    res.body()?.let { cacheVpnConfig(Gson().toJson(it)) }
                    configOk = true
                    Log.i(TAG, "syncConfig OK device=${res.body()?.device_id?.take(8)}")
                }
            }
        }.onFailure { e ->
            Log.w(TAG, "syncConfig: ${e.message}")
        }
        mergeSavedHashesIntoCachedConfig()
        return hashesOk || configOk
    }

    fun clearTunnelApiBase() {
        if (tunnelApiBaseUrl != null) {
            tunnelApiBaseUrl = null
            _api = null
            _apiCacheKey = null
            Log.i(TAG, "API via public URL")
        }
    }

    fun tunnelApiBaseUrl(): String =
        if (shouldUseTunnelApiProxy()) TunnelApiProxy.baseUrl()
        else "http://$WG_TUNNEL_GATEWAY:8000"

    fun shouldUseTunnelApiProxy(): Boolean =
        APP_EXCLUDED_FROM_VPN &&
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            !WdttTunnelManager.isBootstrapMode() &&
            TunnelApiProxy.isActive()

    private suspend fun prepareTunnelApiBase(): Boolean {
        if (!APP_EXCLUDED_FROM_VPN) {
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            return true
        }
        if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) return false
        if (WdttTunnelManager.isBootstrapMode()) return false
        if (TunnelApiProxy.isActive()) {
            useApiBase(TunnelApiProxy.baseUrl())
            invalidateApiClient()
            return true
        }
        if (!TunnelApiProxy.ensureStarted(context, timeoutMs = 30_000L)) return false
        useApiBase(TunnelApiProxy.baseUrl())
        invalidateApiClient()
        Log.i(TAG, "API via local proxy: ${TunnelApiProxy.baseUrl()}")
        return true
    }

    fun invalidateApiClient() {
        _api = null
        _apiCacheKey = null
    }

    /** true когда app excluded из WG и overlay ещё нужен (прокси не поднят). */
    fun needsTunnelApiOverlay(): Boolean =
        APP_EXCLUDED_FROM_VPN &&
            com.silent.vpn.service.SilentVpnService.isRunning &&
            com.silent.vpn.vpn.WdttTunnelManager.tunnelReady.value &&
            !TunnelApiProxy.isActive()

    suspend fun ensureTunnelApiProxy(): Boolean = prepareTunnelApiBase()

    /**
     * Основной VPN: краткий overlay 10.66.66.0/24.
     * Bootstrap: полный overlay через withApiOverlay.
     */
    suspend fun <T> withTunnelApiWhenExcluded(block: suspend () -> T): T =
        withTunnelApiWhenExcludedInternal(block, allowDuringRampUp = false)

    fun isMainVpnTunnelUp(): Boolean =
        com.silent.vpn.service.SilentVpnService.isRunning &&
            com.silent.vpn.vpn.WdttTunnelManager.running.value &&
            com.silent.vpn.vpn.WdttTunnelManager.tunnelReady.value &&
            !com.silent.vpn.vpn.WdttTunnelManager.isBootstrapMode()

    /**
     * Main VPN tunnel API — только proxy/direct bind, без overlay.
     */
    suspend fun <T> withTunnelApiStrict(block: suspend () -> T): T {
        check(isMainVpnTunnelUp()) { "VPN tunnel not up" }
        return withTunnelBackendBlock(block = block)
    }

    /** Backend API для UI/ConfigSync — без overlay (overlay только для withUserBackendApi). */
    suspend fun <T> withBackendApi(block: suspend () -> T): T = withRoutineBackendApi(block = block)

    /** Долгая загрузка APK — overlay без throttle. */
    suspend fun <T> withTunnelApiForUpdateDownload(block: suspend () -> T): T {
        if (!APP_EXCLUDED_FROM_VPN) return block()
        if (!com.silent.vpn.service.SilentVpnService.isRunning) return block()
        if (!com.silent.vpn.vpn.WdttTunnelManager.tunnelReady.value) {
            Log.w(TAG, "withTunnelApiForUpdateDownload: tunnel not ready")
            error("VPN tunnel not ready for update download")
        }
        useApiBase(tunnelApiBaseUrl())
        invalidateApiClient()
        return com.silent.vpn.vpn.WdttTunnelManager.withApiOverlayForDownload { block() }
    }

    private suspend fun <T> withTunnelApiWhenExcludedInternal(
        block: suspend () -> T,
        allowDuringRampUp: Boolean,
    ): T {
        if (!APP_EXCLUDED_FROM_VPN) return block()
        if (!com.silent.vpn.service.SilentVpnService.isRunning) return block()
        if (!com.silent.vpn.vpn.WdttTunnelManager.tunnelReady.value) {
            Log.w(TAG, "withTunnelApiWhenExcluded: tunnel not ready")
            error("VPN tunnel not ready for backend API")
        }
        useApiBase(tunnelApiBaseUrl())
        invalidateApiClient()
        return if (com.silent.vpn.vpn.WdttTunnelManager.isBootstrapMode()) {
            com.silent.vpn.vpn.WdttTunnelManager.withApiOverlay { block() }
        } else {
            if (!prepareTunnelApiBase()) error("tunnel proxy not ready")
            block()
        }
    }

    /** WG API/nginx на сервере всегда 10.66.66.1 (не client_ip−1). */
    fun wgGatewayFromAddress(wgAddress: String?): String? {
        if (wgAddress.isNullOrBlank()) return WG_TUNNEL_GATEWAY
        val host = wgAddress.substringBefore('/').trim()
        if (!host.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) return null
        if (!host.startsWith("10.66.")) return null
        return WG_TUNNEL_GATEWAY
    }

    fun apiBaseCandidates(wgAddress: String? = null): List<String> {
        val out = linkedSetOf<String>()
        if (shouldUseTunnelApiProxy()) {
            out.add(TunnelApiProxy.baseUrl())
        } else if (!APP_EXCLUDED_FROM_VPN) {
            wgGatewayFromAddress(wgAddress)?.let { gw ->
                out.add("http://$gw:8000")
                out.add("https://$gw")
            }
        }
        out.add("https://${BootstrapVpnConfig.serverHost()}")
        out.add("https://$DEFAULT_SERVER_HOST")
        out.add(getPublicServerUrl())
        return out.filter { it.isNotBlank() }.toList()
    }

    fun getPublicServerUrl(): String =
        prefs.getString(PREF_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL

    /** База для скачивания: public HTTPS, или tunnel если проверка/прокси уже через VPN. */
    fun resolveUpdateDownloadBase(preferredBase: String?): String {
        val base = preferredBase?.trimEnd('/').orEmpty()
        if (isMainVpnTunnelUp() && APP_EXCLUDED_FROM_VPN) {
            if (isTunnelApiBase(base) || shouldUseTunnelApiProxy()) return tunnelApiBaseUrl()
            if (base.startsWith("https://")) return base
            return getPublicServerUrl().trimEnd('/')
        }
        if (isTunnelApiBase(base) || shouldUseTunnelApiProxy()) return tunnelApiBaseUrl()
        if (base.startsWith("http://")) {
            if (APP_EXCLUDED_FROM_VPN && !TunnelApiProxy.isActive()) {
                return "https://$DEFAULT_SERVER_HOST"
            }
            return base
        }
        if (base.contains(Regex("""\d+\.\d+\.\d+\.\d+"""))) return "https://$DEFAULT_SERVER_HOST"
        if (base.startsWith("https://")) return base
        return "https://$DEFAULT_SERVER_HOST"
    }

    fun needsOverlayForUpdateDownload(base: String): Boolean =
        needsTunnelApiOverlay() && isTunnelApiBase(base)

    private fun isTunnelApiBase(base: String): Boolean {
        if (base.isBlank()) return false
        if (base.contains(WG_TUNNEL_GATEWAY)) return true
        if (base.contains("127.0.0.1") && base.contains(":${TunnelApiProxy.LISTEN_PORT}")) return true
        return base.startsWith("http://") &&
            base.substringAfter("http://").substringBefore('/').substringBefore(':')
                .matches(Regex("""\d+\.\d+\.\d+\.\d+"""))
    }

    fun joinUpdateUrl(base: String, downloadPath: String): String {
        if (downloadPath.startsWith("http://") || downloadPath.startsWith("https://")) return downloadPath
        val path = if (downloadPath.startsWith("/")) downloadPath else "/$downloadPath"
        return base.trimEnd('/') + path.replace(" ", "%20")
    }

    fun buildDownloadClient(): OkHttpClient {
        val nipHost = DEFAULT_SERVER_HOST
        return OkHttpClient.Builder()
            .addInterceptor { chain ->
                var req = chain.request()
                if (req.url.host.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) {
                    req = req.newBuilder().header("Host", nipHost).build()
                }
                chain.proceed(req)
            }
            .hostnameVerifier { _, _ -> true }
            .sslSocketFactory(TrustAllCerts.sslSocketFactory(), TrustAllCerts.trustManager())
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.MINUTES)
            .build()
    }

    /** Временно переключить base URL (для перебора кандидатов при входе). */
    fun useApiBase(baseUrl: String) {
        val normalized = baseUrl.trimEnd('/')
        if (tunnelApiBaseUrl != normalized) {
            tunnelApiBaseUrl = normalized
            _api = null
            _apiCacheKey = null
        }
    }
    fun setServerUrl(url: String) {
        prefs.edit().putString(PREF_SERVER_URL, url.trimEnd('/')).apply()
        _api = null
        _apiCacheKey = null
    }
    fun ensureServerUrl() {
        if (prefs.getString(PREF_SERVER_URL, null).isNullOrBlank()) {
            setServerUrl(DEFAULT_SERVER_URL)
        }
    }
    fun isServerConfigured() = getServerUrl().isNotEmpty()

    fun getAccessToken(): String? = prefs.getString(PREF_ACCESS_TOKEN, null)
    fun getRefreshToken(): String? = prefs.getString(PREF_REFRESH_TOKEN, null)
    fun saveTokens(access: String, refresh: String) {
        prefs.edit()
            .putString(PREF_ACCESS_TOKEN, access)
            .putString(PREF_REFRESH_TOKEN, refresh)
            .apply()
        _api = null
        _apiCacheKey = null
    }
    fun clearTokens() {
        prefs.edit().remove(PREF_ACCESS_TOKEN).remove(PREF_REFRESH_TOKEN).apply()
        clearCachedProfile()
        _api = null
        _apiCacheKey = null
    }

    fun saveCachedProfile(profile: UserProfile) {
        prefs.edit().putString(PREF_CACHED_PROFILE, Gson().toJson(profile)).apply()
    }

    fun getCachedProfile(): UserProfile? {
        val json = prefs.getString(PREF_CACHED_PROFILE, null) ?: return null
        return runCatching { Gson().fromJson(json, UserProfile::class.java) }.getOrNull()
    }

    fun clearCachedProfile() {
        prefs.edit().remove(PREF_CACHED_PROFILE).apply()
    }

    fun saveCachedTheme(theme: ThemeData) {
        prefs.edit().putString(PREF_CACHED_THEME, Gson().toJson(theme)).apply()
    }

    fun getCachedTheme(): ThemeData? {
        val json = prefs.getString(PREF_CACHED_THEME, null) ?: return null
        return runCatching { Gson().fromJson(json, ThemeData::class.java) }.getOrNull()
    }

    fun isLoggedIn() = getAccessToken() != null

    fun getDeviceFingerprint(): String {
        return prefs.getString(PREF_DEVICE_FP, null)
            ?: throw IllegalStateException("Session not started")
    }

    /** Человекочитаемое имя устройства для списка сессий (напр. «Samsung SM-G991B»). */
    fun getDeviceDisplayName(): String {
        val manufacturer = (android.os.Build.MANUFACTURER ?: "").trim()
        val model = (android.os.Build.MODEL ?: "").trim()
        val raw = when {
            model.isEmpty() -> manufacturer
            manufacturer.isEmpty() -> model
            model.startsWith(manufacturer, ignoreCase = true) -> model
            else -> "$manufacturer $model"
        }.trim()
        return raw.replaceFirstChar { if (it.isLowerCase()) it.titlecase() else it.toString() }
            .ifBlank { "Android" }
            .take(64)
    }

    /**
     * Session fingerprint = СТАБИЛЬНЫЙ id устройства (один телефон = один ряд-сессия).
     * Раньше тут был случайный UUID на каждый вход → перелогин/переустановка плодили
     * «призрачные» сессии и забивали лимит 3-х. Теперь берём стабильный отпечаток.
     */
    fun startNewSession(): String {
        clearCachedVpnConfig()
        clearSessionDeviceId()
        val fp = stableDeviceFingerprint()
        prefs.edit().putString(PREF_DEVICE_FP, fp).apply()
        return fp
    }

    /** ANDROID_ID-based стабильный отпечаток; переживает переустановку и перелогин. */
    private fun stableDeviceFingerprint(): String {
        prefs.getString(PREF_STABLE_FP, null)?.takeIf { it.isNotBlank() }?.let { return it }
        val androidId = try {
            android.provider.Settings.Secure.getString(
                context.contentResolver,
                android.provider.Settings.Secure.ANDROID_ID,
            )
        } catch (e: Exception) {
            null
        }
        val fp = if (!androidId.isNullOrBlank() && androidId != "9774d56d682e549c") {
            "and-$androidId"
        } else {
            "and-${UUID.randomUUID()}"
        }
        prefs.edit().putString(PREF_STABLE_FP, fp).apply()
        return fp
    }

    fun clearSessionFingerprint() {
        prefs.edit().remove(PREF_DEVICE_FP).apply()
    }

    fun hasSessionFingerprint(): Boolean = prefs.getString(PREF_DEVICE_FP, null) != null

    fun saveSessionDeviceId(id: String) {
        prefs.edit().putString(PREF_SESSION_DEVICE_ID, id).apply()
    }

    fun getSessionDeviceId(): String? = prefs.getString(PREF_SESSION_DEVICE_ID, null)?.takeIf { it.isNotBlank() }

    fun clearSessionDeviceId() {
        prefs.edit().remove(PREF_SESSION_DEVICE_ID).apply()
    }

    fun saveLastEmail(email: String) {
        prefs.edit().putString(PREF_LAST_EMAIL, email.trim()).apply()
    }

    fun getRememberMe(): Boolean = prefs.getBoolean(PREF_REMEMBER_ME, false)

    fun saveRememberMe(email: String, password: String, remember: Boolean) {
        prefs.edit()
            .putBoolean(PREF_REMEMBER_ME, remember)
            .apply {
                if (remember) {
                    putString(PREF_LAST_EMAIL, email.trim())
                    putString(PREF_REMEMBERED_PASSWORD, password)
                } else {
                    remove(PREF_LAST_EMAIL)
                    remove(PREF_REMEMBERED_PASSWORD)
                }
            }
            .apply()
    }

    fun getRememberedPassword(): String? =
        if (getRememberMe()) prefs.getString(PREF_REMEMBERED_PASSWORD, null)?.takeIf { it.isNotBlank() } else null

    fun getLastEmail(): String? =
        if (getRememberMe()) prefs.getString(PREF_LAST_EMAIL, null)?.takeIf { it.isNotBlank() } else null

    fun clearCachedVpnConfig() {
        prefs.edit().remove(PREF_CACHED_CONFIG).remove(PREF_CACHED_CONFIG_TS).apply()
    }

    fun getExcludedPackages(): Set<String> =
        prefs.getString(PREF_EXCLUDED_APPS, "")?.split(",")?.filter { it.isNotBlank() }?.toSet() ?: emptySet()

    fun isExclusionsWhitelist(): Boolean = prefs.getBoolean(PREF_EXCLUSIONS_WHITELIST, false)

    fun saveExcludedApps(packages: Set<String>, whitelist: Boolean) {
        prefs.edit()
            .putString(PREF_EXCLUDED_APPS, packages.joinToString(","))
            .putBoolean(PREF_EXCLUSIONS_WHITELIST, whitelist)
            .apply()
    }

    fun getVkUserId(): Long = prefs.getLong(PREF_VK_USER_ID, 0L)
    fun saveVkUserId(id: Long) = prefs.edit().putLong(PREF_VK_USER_ID, id).apply()
    fun getVkAccessToken(): String? = prefs.getString(PREF_VK_ACCESS_TOKEN, null)
    fun saveVkAccessToken(token: String?) {
        prefs.edit().apply {
            if (token.isNullOrBlank()) remove(PREF_VK_ACCESS_TOKEN) else putString(PREF_VK_ACCESS_TOKEN, token)
        }.apply()
    }

    /** VK-хеш для bootstrap VPN на экране входа — зашит в BuildConfig при сборке. */
    fun getBootstrapHash(): String? =
        com.silent.vpn.BuildConfig.BOOTSTRAP_VK_HASH.trim().takeIf { it.isNotBlank() }

    fun saveBootstrapHash(@Suppress("UNUSED_PARAMETER") hash: String?) {
        // Хеш задаётся при сборке (debug — фиксированный, release — -PbootstrapVkHash).
    }

    /** После login bootstrap VPN отключается; embedded-хеш в BuildConfig не трогаем. */
    fun clearBootstrapHash() {
        if (!prefs.contains(PREF_BOOTSTRAP_HASH)) return
        prefs.edit().remove(PREF_BOOTSTRAP_HASH).apply()
    }

    /** Активные серверные хеши для основного VPN (не bootstrap). */
    fun mainVpnServerHashes(): List<String> = com.silent.vpn.vk.HashParser.normalizeList(
        getSavedHashItems().activeServerHashes().map { it.hash.trim() },
    ).filter { it.isNotBlank() }.distinct().take(HashChannelHelper.MAX_HASHES)

    fun hasMainVpnServerHashes(): Boolean = mainVpnServerHashes().isNotEmpty()

    fun saveHashItems(items: List<HashItemDto>) {
        if (items.isEmpty()) return
        prefs.edit()
            .putString(PREF_SAVED_HASH_ITEMS, Gson().toJson(items))
            .putLong(PREF_SAVED_HASH_ITEMS_TS, System.currentTimeMillis())
            .apply()
    }

    fun getSavedHashItems(): List<HashItemDto> {
        val json = prefs.getString(PREF_SAVED_HASH_ITEMS, null) ?: return emptyList()
        return runCatching {
            val type = object : TypeToken<List<HashItemDto>>() {}.type
            Gson().fromJson<List<HashItemDto>>(json, type).sanitized()
        }.getOrDefault(emptyList())
    }

    fun hashItemsFingerprint(items: List<HashItemDto>): String =
        items.activeServerHashes().map { it.hash.trim() }.sorted().joinToString("|")

    /**
     * Хеши для основного VPN: только сохранённые с сервера (PREF_SAVED_HASH_ITEMS).
     * Fallback — vk_hashes из кеша конфига (после merge), без временного bootstrap-хеша.
     */
    fun resolveConnectVkHashes(
        configHashes: List<String>,
        savedItems: List<HashItemDto> = getSavedHashItems(),
    ): List<String> {
        val fromSaved = com.silent.vpn.vk.HashParser.normalizeList(
            savedItems.activeServerHashes().map { it.hash.trim() },
        ).filter { it.isNotBlank() }.distinct().take(HashChannelHelper.MAX_HASHES)
        if (fromSaved.isNotEmpty()) return fromSaved
        val boot = getBootstrapHash()?.trim().orEmpty()
        return com.silent.vpn.vk.HashParser.normalizeList(configHashes)
            .filter { it.isNotBlank() && (boot.isEmpty() || it != boot) }
            .distinct()
            .take(HashChannelHelper.MAX_HASHES)
    }

    /** Обновить vk_hashes в кешированном конфиге после sync хешей с сервера. */
    fun mergeSavedHashesIntoCachedConfig() {
        val hashes = mainVpnServerHashes().ifEmpty { resolveConnectVkHashes(emptyList()) }
        if (hashes.isEmpty()) return
        val json = getCachedVpnConfigRaw() ?: return
        val cfg = runCatching { Gson().fromJson(json, VpnConfig::class.java) }.getOrNull() ?: return
        if (cfg.vk_hashes == hashes) return
        cacheVpnConfig(Gson().toJson(cfg.copy(vk_hashes = hashes)))
        Log.i(TAG, "cached VPN config vk_hashes updated from saved items (${hashes.size})")
    }

    /** JSON конфига без проверки TTL (для merge после OTA). */
    private fun getCachedVpnConfigRaw(): String? =
        prefs.getString(PREF_CACHED_CONFIG, null)?.takeIf { it.isNotBlank() }

    fun getCachedVpnConfig(): String? {
        val ts = prefs.getLong(PREF_CACHED_CONFIG_TS, 0L)
        if (ts > 0L && System.currentTimeMillis() - ts > 7 * 24 * 60 * 60 * 1000L) return null
        return getCachedVpnConfigRaw()
    }

    fun getSavedHashItemsUpdatedAt(): Long = prefs.getLong(PREF_SAVED_HASH_ITEMS_TS, 0L)

    fun getTotalWorkers(activeHashCount: Int = getSavedHashItems().activeServerHashCount().coerceAtLeast(1)): Int {
        val capped = activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES)
        if (!BuildConfig.DEBUG) {
            return HashChannelHelper.normalizeTotalWorkers(
                HashChannelHelper.WORKERS_PER_GROUP * 4,
                capped,
            )
        }
        val max = HashChannelHelper.maxTotalWorkers(capped)
        if (prefs.contains(PREF_HASH_TOTAL_WORKERS)) {
            val raw = prefs.getInt(PREF_HASH_TOTAL_WORKERS, HashChannelHelper.WORKERS_PER_GROUP)
            if (raw > max) {
                saveTotalWorkers(max, capped)
                return max
            }
            return HashChannelHelper.normalizeTotalWorkers(raw, capped)
        }
        if (!prefs.getBoolean(PREF_HASH_LEGACY_MIGRATED, false) &&
            prefs.contains(PREF_HASH_CHANNELS_PER_HASH)
        ) {
            val legacyPer = prefs.getInt(PREF_HASH_CHANNELS_PER_HASH, HashChannelHelper.WORKERS_PER_GROUP)
            val migrated = HashChannelHelper.migrateLegacyPerHash(legacyPer, capped)
            prefs.edit()
                .putInt(PREF_HASH_TOTAL_WORKERS, migrated)
                .putBoolean(PREF_HASH_LEGACY_MIGRATED, true)
                .apply()
            return migrated
        }
        val firstInstall = HashChannelHelper.normalizeTotalWorkers(
            HashChannelHelper.WORKERS_PER_GROUP * 4,
            capped,
        )
        saveTotalWorkers(firstInstall, capped)
        return firstInstall
    }

    fun saveTotalWorkers(value: Int, activeHashCount: Int = getSavedHashItems().activeServerHashCount().coerceAtLeast(1)) {
        prefs.edit()
            .putInt(
                PREF_HASH_TOTAL_WORKERS,
                HashChannelHelper.normalizeTotalWorkers(value, activeHashCount),
            )
            .apply()
    }

    /** `-n` для libclient: итого потоков (кратно 9), как в reference WDTT. */
    fun resolveWorkersForLibclient(vkHashCount: Int): Int {
        val savedActive = getSavedHashItems().activeServerHashCount()
        val activeHashes = maxOf(vkHashCount, savedActive, 1).coerceAtMost(HashChannelHelper.MAX_HASHES)
        return HashChannelHelper.workersForLibclient(getTotalWorkers(activeHashes), activeHashes)
    }

    fun clearSavedHashItems() {
        prefs.edit()
            .remove(PREF_SAVED_HASH_ITEMS)
            .remove(PREF_SAVED_HASH_ITEMS_TS)
            .apply()
    }

    /** POST /disconnect — public HTTPS, затем tunnel (как PC). */
    suspend fun notifyDisconnectBeforeTunnelStop(): Boolean {
        if (!isLoggedIn()) return false
        if (postDisconnectViaPublic()) return true
        if (!isMainVpnTunnelUp()) {
            Log.w(TAG, "disconnect: tunnel not up")
            return false
        }
        return runCatching {
            withTunnelBackendBlock {
                val url = getServerUrl()
                val ok = postDisconnectRequest()
                Log.i(TAG, "disconnect via $url ok=$ok")
                ok
            }
        }.getOrOrLog(false)
    }

    /**
     * Полная синхронизация после включения главного VPN (как при login, но без overlay):
     * POST /connect → хеши → config → profile → theme через proxy / direct bind.
     */
    suspend fun syncAllViaTunnel(): Boolean = tunnelSyncMutex.withLock {
        if (!isLoggedIn()) return@withLock false
        prepareTunnelApiFromCachedConfig()
        invalidatePublicReachabilityCache()

        if (!isOnMobileData() && postConnectViaPublic()) {
            return@withLock runCatching {
                syncHashesAndConfigAfterConnect()
                syncProfileAndThemeAfterConnect()
                Log.i(TAG, "syncAll OK (public connect + hashes/profile)")
                true
            }.getOrOrLog(false)
        }

        if (!isMainVpnTunnelUp()) return@withLock false

        Log.i(
            TAG,
            "syncAllViaTunnel: excluded=$APP_EXCLUDED_FROM_VPN mobile=${isOnMobileData()} proxy=${TunnelApiProxy.isActive()}",
        )

        return@withLock runCatching {
            withTunnelBackendBlock {
                val url = getServerUrl()
                val online = postConnectOnlineViaTunnel()
                if (!online) {
                    Log.w(TAG, "syncAll: POST /connect failed via $url — continue hashes/profile")
                }
                val hashesOk = syncHashesAndConfigAfterConnect()
                val profileOk = syncProfileAndThemeAfterConnect()
                val ok = online || hashesOk || profileOk
                Log.i(TAG, "syncAll via $url (connect=$online hashes=$hashesOk profile=$profileOk)")
                ok
            }
        }.getOrOrLog(false)
    }

    private suspend fun postConnectViaPublic(): Boolean {
        val body = ConnectRequest(getDeviceFingerprint(), "android")
        for (base in publicApiBases()) {
            val res = runCatching {
                buildApi("$base/").connect(body)
            }.getOrNull() ?: continue
            if (res.isSuccessful) {
                Log.i(TAG, "POST /connect OK (public $base)")
                return true
            }
            val err = runCatching { res.errorBody()?.string()?.take(200) }.getOrNull()
            Log.w(TAG, "POST /connect public HTTP ${res.code()} on $base${err?.let { ": $it" } ?: ""}")
        }
        return false
    }

    private suspend fun postDisconnectViaPublic(): Boolean {
        val body = DisconnectRequest(getDeviceFingerprint())
        for (base in publicApiBases()) {
            val res = runCatching {
                buildApi("$base/").disconnect(body)
            }.getOrNull() ?: continue
            if (res.isSuccessful) {
                Log.i(TAG, "POST /disconnect OK (public $base)")
                return true
            }
            Log.w(TAG, "disconnect public HTTP ${res.code()} on $base")
        }
        return false
    }

    private suspend fun postConnectOnlineViaTunnel(): Boolean {
        val res = runCatching {
            getApi().connect(ConnectRequest(getDeviceFingerprint(), "android"))
        }.getOrNull() ?: return false
        if (res.isSuccessful) {
            Log.i(TAG, "POST /connect OK (tunnel)")
            return true
        }
        val err = runCatching { res.errorBody()?.string()?.take(200) }.getOrNull()
        Log.w(TAG, "POST /connect tunnel HTTP ${res.code()}${err?.let { ": $it" } ?: ""}")
        return false
    }

    private suspend fun syncProfileAndThemeAfterConnect(): Boolean {
        return runCatching {
            withRoutineBackendApi {
                var ok = false
                val profileRes = getApi().getProfile()
                if (profileRes.isSuccessful) {
                    profileRes.body()?.let { saveCachedProfile(it) }
                    Log.i(TAG, "syncAll profile OK")
                    ok = true
                } else {
                    Log.w(TAG, "syncAll profile HTTP ${profileRes.code()}")
                }
                val themeRes = getApi().getTheme()
                if (themeRes.isSuccessful) {
                    themeRes.body()?.let { saveCachedTheme(it) }
                    Log.i(TAG, "syncAll theme OK")
                    ok = true
                }
                ok
            }
        }.onFailure { e -> Log.w(TAG, "syncAll profile/theme: ${e.message}") }
            .getOrDefault(false)
    }

    private fun <T> Result<T>.getOrOrLog(default: T): T =
        onFailure { e -> Log.w(TAG, "tunnel API: ${e.message}") }.getOrDefault(default)

    private suspend fun postDisconnectRequest(): Boolean {
        val res = getApi().disconnect(DisconnectRequest(getDeviceFingerprint()))
        if (res.isSuccessful) return true
        Log.w(TAG, "disconnect HTTP ${res.code()}")
        return false
    }

    suspend fun fetchAndSaveHashItemsViaTunnel(): Result<List<HashItemDto>> {
        return if (WdttTunnelManager.isBootstrapMode()) {
            runCatching {
                withTunnelApiWhenExcludedInternal({
                    fetchHashItemsFromBases(listOf("http://$WG_TUNNEL_GATEWAY:8000")).getOrThrow()
                }, allowDuringRampUp = true)
            }.fold(
                onSuccess = { Result.success(it) },
                onFailure = { Result.failure(it) },
            )
        } else {
            fetchHashItemsViaTunnel().fold(
                onSuccess = { Result.success(it) },
                onFailure = { e -> Result.failure(e) },
            )
        }
    }

    /** Хеши через VPN: proxy → direct 10.66.66.1 (bind), без overlay. */
    private suspend fun fetchHashItemsViaTunnel(): Result<List<HashItemDto>> =
        runCatching {
            if (prepareTunnelApiBase()) {
                fetchHashItemsFromBases(listOf(TunnelApiProxy.baseUrl())).getOrNull()?.let { return@runCatching it }
                Log.w(TAG, "hash via proxy failed, try direct gateway")
            }
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            fetchHashItemsOnce().getOrThrow()
        }.fold(
            onSuccess = { items ->
                Log.i(TAG, "fetchAndSaveHashItems OK via tunnel (${items.size} items)")
                Result.success(items)
            },
            onFailure = { e ->
                Log.w(TAG, "fetchHashItemsViaTunnel: ${e.message}")
                Result.failure(e)
            },
        )

    suspend fun fetchAndSaveHashItems(): Result<List<HashItemDto>> =
        fetchAndSaveHashItems(preferPublicOnly = false)

    suspend fun fetchAndSaveHashItems(preferPublicOnly: Boolean = false): Result<List<HashItemDto>> {
        if (preferPublicOnly) {
            return fetchHashItemsFromPublicBases(fastTimeout = true)
        }
        return runCatching {
            if (!isPublicBackendReachable() && isMainVpnTunnelUp() && APP_EXCLUDED_FROM_VPN) {
                withRoutineBackendApi {
                    fetchHashItemsOnce().getOrThrow()
                }
            } else {
                withRoutineBackendApi {
                    fetchHashItemsFromBases(apiBaseCandidates(), connectTimeoutSec = 12L).getOrThrow()
                }
            }
        }.fold(
            onSuccess = { Result.success(it) },
            onFailure = { e ->
                Log.w(TAG, "fetchAndSaveHashItems: ${e.message}")
                Result.failure(e)
            },
        )
    }

    private suspend fun fetchHashItemsFromPublicBases(fastTimeout: Boolean): Result<List<HashItemDto>> {
        val bases = if (fastTimeout) {
            listOf("https://$DEFAULT_SERVER_HOST", getPublicServerUrl())
        } else {
            listOf(getPublicServerUrl(), "https://$DEFAULT_SERVER_HOST") +
                apiBaseCandidates().filter { it.startsWith("https://") }
        }.distinct()
        val timeout = if (fastTimeout) 2L else 10L
        return runCatching {
            withBackendApi {
                fetchHashItemsFromBases(bases, connectTimeoutSec = timeout)
            }
        }.getOrElse { e ->
            Log.w(TAG, "fetchAndSaveHashItems public: ${e.message}")
            Result.failure(e)
        }
    }

    /** Обновить access_token по refresh_token (401 на /hashes и т.п.). */
    private suspend fun refreshAccessToken(): Boolean {
        val refresh = getRefreshToken()?.takeIf { it.isNotBlank() } ?: return false
        return try {
            val url = getServerUrl().trimEnd('/')
            val network = resolveVpnNetworkForApi(url)
            val res = buildApi("$url/", vpnNetwork = network).refresh(RefreshRequest(refresh))
            if (!res.isSuccessful) return false
            val body = res.body() ?: return false
            saveTokens(body.access_token, body.refresh_token)
            true
        } catch (e: Exception) {
            Log.w(TAG, "refreshAccessToken: ${e.message}")
            false
        }
    }

    private suspend fun fetchHashItemsOnce(api: SilentApi = getApi()): Result<List<HashItemDto>> {
        return try {
            val res = api.getVpnHashes()
            if (res.code() == 401 && refreshAccessToken()) {
                val retry = api.getVpnHashes()
                if (!retry.isSuccessful) {
                    return Result.failure(
                        Exception(retry.errorBody()?.string()?.take(200) ?: "HTTP ${retry.code()}"),
                    )
                }
                val items = retry.body()!!.toHashItems()
                if (items.isNotEmpty()) saveHashItems(items)
                return Result.success(items)
            }
            if (!res.isSuccessful) {
                return Result.failure(
                    Exception(res.errorBody()?.string()?.take(200) ?: "HTTP ${res.code()}"),
                )
            }
            val items = res.body()!!.toHashItems()
            if (items.isNotEmpty()) saveHashItems(items)
            Result.success(items)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private suspend fun fetchHashItemsFromBases(
        bases: List<String>,
        vpnNetwork: Network? = null,
        connectTimeoutSec: Long? = null,
    ): Result<List<HashItemDto>> {
        val previousTunnel = tunnelApiBaseUrl
        var lastError: Exception? = null
        var succeeded = false
        try {
            for (base in bases.distinct().filter { it.isNotBlank() }) {
                try {
                    val normalized = base.trimEnd('/')
                    val api = if (vpnNetwork != null) {
                        buildApi("$normalized/", vpnNetwork, connectTimeoutSec)
                    } else {
                        useApiBase(normalized)
                        invalidateApiClient()
                        if (connectTimeoutSec != null) {
                            buildApi("$normalized/", connectTimeoutSec = connectTimeoutSec)
                        } else {
                            getApi()
                        }
                    }
                    val attempt = fetchHashItemsOnce(api)
                    if (attempt.isSuccess) {
                        succeeded = true
                        return attempt
                    }
                    lastError = attempt.exceptionOrNull() as? Exception
                        ?: Exception(attempt.toString())
                } catch (e: Exception) {
                    lastError = e
                    Log.w(TAG, "fetchAndSaveHashItems on $base: ${e.message}")
                }
            }
            return Result.failure(lastError ?: Exception("Не удалось загрузить хеши"))
        } finally {
            if (!succeeded && vpnNetwork == null && tunnelApiBaseUrl != previousTunnel) {
                tunnelApiBaseUrl = previousTunnel
                _api = null
                _apiCacheKey = null
            }
        }
    }

    fun humanizeHashFetchError(message: String?): String {
        val m = message?.lowercase().orEmpty()
        val vpnUp = isMainVpnTunnelUp()
        return when {
            m.contains("overlay blocked") ->
                "Подождите завершения подключения VPN и повторите."
            m.contains("tunnel not ready") ->
                "VPN ещё подключается — подождите и повторите."
            m.contains("upstream error") ||
                m.contains("upstream failed") ||
                m.contains("vpn upstream") ||
                m.contains("502") ->
                "Не удалось достучаться до сервера через VPN. Подождите 5 сек и повторите."
            m.contains("overlay suppressed") ->
                "VPN выключается — повторите позже."
            m.contains("failed to connect") ||
                m.contains("connect timed out") ||
                m.contains("unable to resolve") ||
                m.contains("connection refused") ||
                m.contains("network is unreachable") ||
                m.contains("all api routes failed") ||
                m.contains("tunnel api unavailable") ->
                if (vpnUp) {
                    val detail = message?.take(80)?.trim().orEmpty()
                    if (detail.isNotBlank()) {
                        "Не удалось обновить данные: $detail"
                    } else {
                        "Не удалось связаться с сервером. Повторите через несколько секунд."
                    }
                } else {
                    "Нет связи с сервером. При блокировке мобильного интернета включите VPN и повторите."
                }
            else -> message?.take(120) ?: "Не удалось загрузить хеши"
        }
    }

    suspend fun reportHashFailure(hash: String, errorType: String, message: String): Result<Unit> {
        if (!isLoggedIn()) return Result.failure(IllegalStateException("not logged in"))
        if (!allowsBackgroundConfigSync()) {
            return Result.failure(IllegalStateException("hash report deferred until Wi‑Fi or VPN"))
        }
        return runCatching {
            withBackendApi {
                reportHashFailureDirect(hash, errorType, message)
            }
        }
    }

    suspend fun reportHashFailuresBatch(
        items: List<Triple<String, String, String>>,
    ): Result<Unit> {
        if (!isLoggedIn() || items.isEmpty()) return Result.success(Unit)
        if (!allowsBackgroundConfigSync()) {
            return Result.failure(IllegalStateException("hash report batch deferred until Wi‑Fi or VPN"))
        }
        return runCatching {
            withBackendApi {
                items.forEach { (hash, errorType, message) ->
                    reportHashFailureDirect(hash, errorType, message)
                }
            }
        }
    }

    suspend fun reportHashFailuresDirect(items: List<Triple<String, String, String>>) {
        items.forEach { (hash, errorType, message) ->
            reportHashFailureDirect(hash, errorType, message)
        }
    }

    internal suspend fun reportHashFailureDirect(hash: String, errorType: String, message: String) {
        val req = HashFailureReportRequest(
            hash = hash,
            error_type = errorType,
            message = message,
            device_fingerprint = getDeviceFingerprint(),
        )
        val res = getApi().reportHashFailure(req)
        if (!res.isSuccessful) {
            throw Exception("report-failure ${res.code()}: ${res.errorBody()?.string()}")
        }
    }

    /** Stable fingerprint for bootstrap and login — один and-ANDROID_ID на телефон. */
    fun getOrCreatePreLoginFingerprint(): String {
        prefs.getString(PREF_STABLE_FP, null)?.takeIf { it.isNotBlank() }?.let { return it }
        return stableDeviceFingerprint()
    }

    fun cacheVpnConfig(json: String) {
        prefs.edit()
            .putString(PREF_CACHED_CONFIG, json)
            .putLong(PREF_CACHED_CONFIG_TS, System.currentTimeMillis())
            .apply()
    }

    fun getClipboardText(): String? {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return null
        val clip = cm.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        return clip.getItemAt(0).coerceToText(context)?.toString()
    }

    fun getSyncHashesRev(): Long = prefs.getLong(PREF_SYNC_HASHES_REV, 0L)
    fun getSyncThemeRev(): Long = prefs.getLong(PREF_SYNC_THEME_REV, 0L)
    fun getSyncProfileRev(): Long = prefs.getLong(PREF_SYNC_PROFILE_REV, 0L)

    fun saveSyncHashesRev(rev: Long) {
        prefs.edit().putLong(PREF_SYNC_HASHES_REV, rev).apply()
    }

    fun saveSyncThemeRev(rev: Long) {
        prefs.edit().putLong(PREF_SYNC_THEME_REV, rev).apply()
    }

    fun saveSyncProfileRev(rev: Long) {
        prefs.edit().putLong(PREF_SYNC_PROFILE_REV, rev).apply()
    }

    fun clearSyncRevisions() {
        prefs.edit()
            .remove(PREF_SYNC_HASHES_REV)
            .remove(PREF_SYNC_THEME_REV)
            .remove(PREF_SYNC_PROFILE_REV)
            .apply()
    }

    /** После VPN на mobile (public недоступен): хеши + профиль через proxy, без overlay. */
    suspend fun pullAfterTunnelReady(): Boolean {
        if (!isLoggedIn()) return false
        if (isPublicBackendReachable()) {
            Log.d(TAG, "pullAfterTunnelReady: skip — public API OK")
            return false
        }
        if (!isMainVpnTunnelUp()) return false
        var ok = false
        runCatching {
            withRoutineBackendApi {
                val items = fetchHashItemsOnce().getOrThrow()
                if (items.isNotEmpty()) {
                    mergeSavedHashesIntoCachedConfig()
                    runCatching {
                        fetchSyncStateInternal()?.hashes?.let { saveSyncHashesRev(it) }
                    }
                    Log.i(TAG, "pullAfterTunnelReady: hashes OK (${items.size})")
                    ok = true
                }
            }
        }.onFailure { e ->
            Log.w(TAG, "pullAfterTunnelReady hashes: ${e.message}")
        }
        fetchAndSaveProfileViaTunnel().onSuccess {
            Log.i(TAG, "pullAfterTunnelReady: profile OK (online=${it.devices.count { d -> d.is_connected }})")
            ok = true
        }.onFailure { e ->
            Log.w(TAG, "pullAfterTunnelReady profile: ${e.message}")
        }
        return ok
    }

    /** Профиль напрямую через текущий API base (внутри ephemeral/bootstrap tunnel). */
    suspend fun fetchProfileDirect(): Result<UserProfile> = runCatching {
        fetchProfileInternal()
    }

    /** Профиль с сервера — без fallback на кеш; тот же канал, что сессии. */
    suspend fun fetchProfileLive(): Result<UserProfile> = runCatching {
        withRoutineBackendApi(block = { fetchProfileInternal() })
    }

    /** Профиль при активном VPN (promo/подписка/контроль доступа) — с overlay fallback. */
    suspend fun fetchProfileLiveViaUser(): Result<UserProfile> = runCatching {
        withUserBackendApi { fetchProfileInternal() }
    }

    private suspend fun fetchProfileInternal(): UserProfile {
        var res = getApi().getProfile()
        if (res.code() == 401 && refreshAccessToken()) {
            invalidateApiClient()
            res = getApi().getProfile()
        }
        if (!res.isSuccessful) error("profile HTTP ${res.code()}")
        val body = res.body() ?: error("profile empty")
        saveCachedProfile(body)
        Log.i(TAG, "fetchProfileLive OK via ${getServerUrl()} online=${body.devices.count { it.is_connected }}")
        return body
    }

    /** Профиль: public или tunnel proxy, без overlay. */
    suspend fun fetchAndSaveProfileViaTunnel(): Result<UserProfile> = fetchProfileLive()

    /** Один запрос revision — тот же канал, что профиль/сессии. */
    suspend fun fetchSyncState(): Result<SyncStateResponse> = configSyncMutex.withLock {
        runCatching { fetchSyncStateInternal() ?: error("sync-state empty") }
    }

    private suspend fun fetchSyncStateInternal(): SyncStateResponse? =
        withRoutineBackendApi {
            var res = getApi().getSyncState(
                hashesSince = getSyncHashesRev(),
                themeSince = getSyncThemeRev(),
                profileSince = getSyncProfileRev(),
            )
            if (res.code() == 401 && refreshAccessToken()) {
                invalidateApiClient()
                res = getApi().getSyncState(
                    hashesSince = getSyncHashesRev(),
                    themeSince = getSyncThemeRev(),
                    profileSince = getSyncProfileRev(),
                )
            }
            if (!res.isSuccessful) {
                error("sync-state HTTP ${res.code()}")
            }
            res.body()
        }

    /** Хеши — тот же withRoutineBackendApi, что /users/me (сессии). */
    suspend fun fetchAndSaveHashItemsForSync(): Result<List<HashItemDto>> = configSyncMutex.withLock {
        runCatching {
            withRoutineBackendApi {
                fetchHashItemsOnce().getOrThrow()
            }
        }
    }

    /** Сравнение с сохранёнными — fallback когда sync-state недоступен (mobile+VPN). */
    suspend fun refreshHashesIfChanged(): Result<List<HashItemDto>> = configSyncMutex.withLock {
        runCatching {
            val before = hashItemsFingerprint(getSavedHashItems())
            val items = withRoutineBackendApi {
                fetchHashItemsOnce().getOrThrow()
            }
            val after = hashItemsFingerprint(items)
            if (items.isEmpty() || after == before) {
                return@runCatching emptyList<HashItemDto>()
            }
            mergeSavedHashesIntoCachedConfig()
            runCatching { fetchSyncStateInternal()?.hashes?.let { saveSyncHashesRev(it) } }
            items
        }
    }

    private suspend fun <T> withConfigSyncApi(block: suspend () -> T): T = withRoutineBackendApi(block = block)

    suspend fun fetchAndSaveThemeViaSync(): Result<ThemeData> = configSyncMutex.withLock {
        runCatching {
            withConfigSyncApi {
                val res = getApi().getTheme()
                if (!res.isSuccessful) error("theme HTTP ${res.code()}")
                val body = res.body() ?: error("theme empty")
                saveCachedTheme(body)
                body
            }
        }
    }

    suspend fun fetchAndSaveProfileViaSync(): Result<UserProfile> = configSyncMutex.withLock {
        runCatching {
            withConfigSyncApi {
                val res = getApi().getProfile()
                if (!res.isSuccessful) error("profile HTTP ${res.code()}")
                val body = res.body() ?: error("profile empty")
                saveCachedProfile(body)
                body
            }
        }
    }
}

object TrustAllCerts {
    private val trustAll = arrayOf<javax.net.ssl.TrustManager>(
        object : javax.net.ssl.X509TrustManager {
            override fun checkClientTrusted(c: Array<java.security.cert.X509Certificate>, a: String) {}
            override fun checkServerTrusted(c: Array<java.security.cert.X509Certificate>, a: String) {}
            override fun getAcceptedIssuers(): Array<java.security.cert.X509Certificate> = arrayOf()
        }
    )

    fun sslSocketFactory(): javax.net.ssl.SSLSocketFactory {
        val sslContext = javax.net.ssl.SSLContext.getInstance("TLS")
        sslContext.init(null, trustAll, java.security.SecureRandom())
        return sslContext.socketFactory
    }

    fun trustManager() = trustAll[0] as javax.net.ssl.X509TrustManager
}
