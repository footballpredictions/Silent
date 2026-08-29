package com.silent.vpn.data

import android.content.Context
import android.content.ClipboardManager
import android.content.SharedPreferences
import android.net.ConnectivityManager
import android.net.Network
import android.telephony.TelephonyManager
import android.util.Log
import com.silent.vpn.BuildConfig
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.silent.vpn.policy.ApiRoutePolicy
import com.silent.vpn.policy.OlcrtcSessionPolicy
import com.silent.vpn.policy.TunnelHttpPolicy
import com.silent.vpn.policy.UpdateUrlResolver
import com.silent.vpn.vpn.TunnelApiProxy
import com.silent.vpn.vpn.OlcrtcTunnelManager
import com.silent.vpn.vpn.VpnNetworkHelper
import com.silent.vpn.vpn.WdttTunnelManager
import com.silent.vpn.sync.MobileSyncLog
import com.silent.vpn.sync.TunnelSyncResult
import com.silent.vpn.service.VpnSessionState
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

@Singleton
class SilentRepository @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        private const val TAG = "SilentRepository"
        const val DEFAULT_SERVER_URL = "https://132-243-234-162.nip.io"
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
        /** Правила обхода сайтов: домен / IP / CIDR / wildcard, по одному на строку. */
        const val PREF_BYPASS_ROUTES = "bypass_routes"
        const val PREF_SAVED_HASH_ITEMS = "saved_hash_items"
        const val PREF_SAVED_HASH_ITEMS_TS = "saved_hash_items_ts"
        const val PREF_HASH_CHANNELS_PER_HASH = "hash_channels_per_hash"
        const val PREF_HASH_TOTAL_WORKERS = "hash_total_workers"
        const val PREF_HASH_LEGACY_MIGRATED = "hash_total_workers_legacy_migrated"
        /** vkcalls = VKCalls без капчи (default), auto = WBV auto+manual, manual = только ручная капча */
        const val PREF_VK_CRED_STRATEGY = "vk_cred_strategy"
        const val VK_CRED_VKCALLS = "vkcalls"
        const val VK_CRED_AUTO = "auto"
        const val VK_CRED_MANUAL = "manual"

        const val PREF_BYPASS_FAMILY = "bypass_family"
        const val BYPASS_FAMILY_WDTT = "wdtt"
        const val BYPASS_FAMILY_OLCRTC = "olcrtc"
        const val BYPASS_FAMILY_OLCRTC2 = "olcrtc2"
        const val PREF_PREFERRED_SERVER = "preferred_server"
        const val PREF_SERVER_IPS = "vpn_server_ips_json"
        const val SERVER_MAIN = "server1"
        const val SERVER_CELL_PREFIX = "cell:"
        private val PREFERRED_SERVER_SLOT = Regex("^server\\d+$", RegexOption.IGNORE_CASE)
        val BAKED_SERVER_IPS = mapOf(
            "server1" to "132.243.234.162",
            "server2" to "87.58.213.193",
            "server3" to "78.17.74.27",
        )
        private val IPV4_RE = Regex("""\b(\d{1,3}(?:\.\d{1,3}){3})\b""")

        fun normalizePreferredServer(raw: String?): String {
            val v = raw?.trim()?.lowercase().orEmpty()
            if (v.isEmpty() || v == "queen" || v == "main") return SERVER_MAIN
            if (PREFERRED_SERVER_SLOT.matches(v)) return v
            return SERVER_MAIN
        }

        fun slotFromSelectedServer(selected: String?): String? {
            val v = selected?.trim()?.lowercase().orEmpty()
            if (v.isEmpty() || v == "queen" || v == "main") return SERVER_MAIN
            if (PREFERRED_SERVER_SLOT.matches(v)) return v
            return null
        }
        const val PREF_OLCRTC_PROVIDER = "olcrtc_provider"
        const val OLCRTC_WBSTREAM = "wbstream"
        const val OLCRTC_TELEMOST = "telemost"
        /** @deprecated Jitsi убран — старые prefs мигрируют в telemost */
        const val OLCRTC_JITSI = "jitsi"

        /** @deprecated используйте VK_CRED_* */
        const val PREF_CAPTCHA_BYPASS_MODE = "captcha_bypass_mode"
        const val CAPTCHA_MODE_RJS = "rjs"
        const val CAPTCHA_MODE_WV = "wv"
        const val PREF_CACHED_PROFILE = "cached_profile_json"
        /** 402/отзыв: не поднимать «оплачено» из старого client_sync в WG-кеше. */
        const val PREF_VPN_ACCESS_DENIED = "vpn_access_denied"
        const val PREF_CACHED_THEME = "cached_theme_json"
        const val PREF_STANDBY_API_URLS = "standby_api_urls"
        /** Если Улей не открывается до первой theme — известные соты на проде. */
        val BAKED_STANDBY_API_URLS = listOf(
            "http://87.58.213.193:9100",
            "http://78.17.74.27:9100",
        )
        const val PREF_CACHED_REFERRAL = "cached_referral_json"
        const val PREF_APPEARANCE_MODE = "appearance_mode"
        const val PREF_DNS_PRESET = "dns_preset"
        /** Свой DNS пользователя: адреса через запятую. */
        const val PREF_DNS_CUSTOM = "dns_custom_servers"
        const val PREF_SYNC_HASHES_REV = "config_sync_hashes_rev"
        const val PREF_SYNC_THEME_REV = "config_sync_theme_rev"
        const val PREF_SYNC_PROFILE_REV = "config_sync_profile_rev"
        const val PREF_EPHEMERAL_SYNC_LAST_MS = "ephemeral_sync_last_ms"
        const val PREF_PENDING_PAYMENT_LABEL = "pending_payment_label"
        /** Минимальный интервал между авто ephemeral bootstrap (кнопка «Обновить» — без лимита). */
        const val EPHEMERAL_SYNC_MIN_MS = 30 * 60 * 1000L
        const val VK_APP_ID = 54610377L
        const val VK_GROUP_ID = 239092728L
        const val WG_TUNNEL_GATEWAY = "10.66.66.1"
        /** Wi‑Fi main: true (public API). LTE/bootstrap: false (приложение в WG → 10.66.66.1). */
        var APP_EXCLUDED_FROM_VPN = true

        fun applyAppVpnExclusion(isBootstrap: Boolean, onMobileData: Boolean): Boolean {
            val next = com.silent.vpn.policy.AppVpnExclusionPolicy.shouldExcludeApp(
                isBootstrap = isBootstrap,
                onMobileData = onMobileData,
            )
            val changed = APP_EXCLUDED_FROM_VPN != next
            APP_EXCLUDED_FROM_VPN = next
            return changed
        }

        /** Сериализация config-sync — не параллелить с overlay/connect. */
        private val configSyncMutex = Mutex()
    }

    private val prefs: SharedPreferences = createPrefs(context)

    private var _api: SilentApi? = null
    private var _apiCacheKey: String? = null
    private var _baseUrl: String = ""
    /** Когда VPN поднят — API через адрес в туннеле (10.66.66.1), иначе nip.io недоступен в белых списках. */
    private var tunnelApiBaseUrl: String? = null
    @Volatile private var liveProfileAppliedAtMs = 0L

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

    /** Excluded app: без Network.bind/socketFactory (EPERM); mobileApiRoute в WG → прямой 10.66.66.1. */
    private fun resolveVpnNetworkForApi(url: String): Network? {
        if (APP_EXCLUDED_FROM_VPN) return null
        if (!isMainVpnTunnelUp()) return null
        if (url.startsWith(TunnelApiProxy.baseUrl())) return null
        if (!url.contains(WG_TUNNEL_GATEWAY)) return null
        return VpnNetworkHelper.getSilentVpnNetwork(context)
    }

    private fun buildApi(
        baseUrl: String,
        vpnNetwork: Network? = null,
        connectTimeoutSec: Long? = null,
        readTimeoutSec: Long? = null,
    ): SilentApi {
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
                chain.proceed(req)
            }
            .hostnameVerifier { _, _ -> true }
            .sslSocketFactory(TrustAllCerts.sslSocketFactory(), TrustAllCerts.trustManager())
        vpnNetwork?.let { builder.socketFactory(it.socketFactory) }
        val connectSec = connectTimeoutSec ?: if (baseUrl.contains("10.66.")) 12L else 4L
        val readSec = readTimeoutSec ?: 20L
        builder
            .connectTimeout(connectSec, TimeUnit.SECONDS)
            .readTimeout(readSec, TimeUnit.SECONDS)
            .callTimeout((readSec + connectSec + 5).coerceAtMost(180L), TimeUnit.SECONDS)
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

    /** ConfigSync, профиль, сессии — Wi‑Fi public; mobile + VPN — overlay-сессия / tunnel. */
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
                if (APP_EXCLUDED_FROM_VPN && isOnMobileData() && !WdttTunnelManager.isApiOverlayActive()) {
                    error("mobile routine API deferred — use initial sync overlay session")
                }
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

    /** Промокод, подписка, оплата, сессии — один overlay на LTE при явном действии пользователя. */
    suspend fun <T> withUserBackendApi(block: suspend () -> T): T {
        if (VpnSessionState.initialOverlaySyncActive) {
            if (WdttTunnelManager.isApiOverlayActive()) {
                useApiBase(tunnelApiBase())
                invalidateApiClient()
                return block()
            }
            error("user API deferred — initial overlay sync in progress")
        }
        if (APP_EXCLUDED_FROM_VPN && isOnMobileData() && isMainVpnTunnelUp() &&
            !WdttTunnelManager.isApiOverlayActive()
        ) {
            return WdttTunnelManager.withApiOverlayBrief(
                block = {
                    if (TunnelApiProxy.isActive()) {
                        TunnelApiProxy.stopAndAwait()
                    }
                    prepareMainVpnDirectApi()
                    block()
                },
                allowDuringRampUp = true,
                skipIntervalThrottle = true,
            )
        }
        return withRoutineBackendApi(allowOverlayFallback = false, block = block)
    }

    /**
     * Проверка промокода.
     * Живой main VPN не трогаем: только локальный proxy bind к уже поднятому WG.
     * Overlay/startTunnel здесь запрещён — он мигает иконку и рвёт handshake.
     */
    suspend fun <T> withPromoCheckApi(block: suspend () -> T): T {
        if (isMainVpnTunnelUp() && !WdttTunnelManager.isBootstrapMode()) {
            val proxyOk = prepareTunnelApiBaseLegacyProxy()
            if (proxyOk) {
                MobileSyncLog.i("promo", "proxy promo API url=${getServerUrl()} (no overlay)")
                return runCatching { block() }.getOrElse { e ->
                    val msg = e.message.orEmpty()
                    val retryPublic = isTunnelUpstreamError(msg) ||
                        msg.contains("Failed to connect", ignoreCase = true) ||
                        e is java.io.IOException
                    if (retryPublic && !isOnMobileData() && isPublicBackendReachable()) {
                        useApiBase(getPublicServerUrl())
                        invalidateApiClient()
                        MobileSyncLog.w("promo", "proxy failed, public fallback: ${e.message}")
                        return@getOrElse block()
                    }
                    throw e
                }
            }
            if (!isOnMobileData() && isPublicBackendReachable()) {
                useApiBase(getPublicServerUrl())
                invalidateApiClient()
                return block()
            }
            error("failed to connect")
        }
        return withUserBackendApi(block)
    }

    fun canUseMobileDirectTunnelApi(): Boolean =
        ApiRoutePolicy.canUseMobileDirectTunnelApi(apiRouteContext())

    private fun apiRouteContext(): ApiRoutePolicy.RouteContext =
        ApiRoutePolicy.RouteContext(
            onMobileData = isOnMobileData(),
            appExcludedFromVpn = APP_EXCLUDED_FROM_VPN,
            mainVpnTunnelUp = isMainVpnTunnelUp(),
            tunnelDataSyncCompleted = VpnSessionState.tunnelDataSyncCompleted,
            apiOverlayActive = WdttTunnelManager.isApiOverlayActive(),
            bootstrapMode = WdttTunnelManager.isBootstrapMode(),
            tunnelReady = WdttTunnelManager.tunnelReady.value,
            publicReachable = publicReachableCache,
        )

    private fun otaUrlInput(preferredBase: String? = null) = UpdateUrlResolver.OtaUrlInput(
        onMobileData = isOnMobileData(),
        appExcludedFromVpn = APP_EXCLUDED_FROM_VPN,
        mainVpnTunnelUp = isMainVpnTunnelUp(),
        isBootstrapMode = WdttTunnelManager.isBootstrapMode(),
        publicServerUrl = getPublicServerUrl(),
        preferredHttpsBase = preferredBase,
        tunnelProxyActive = shouldUseTunnelApiProxy(),
        otaPlatform = getOtaPlatform(),
    )

    /** App in tunnel — direct; excluded LTE — overlay или mobileApiRoute после sync. */
    private suspend fun <T> withTunnelBackendBlock(
        allowOverlayFallback: Boolean = false,
        block: suspend () -> T,
    ): T {
        if (!isMainVpnTunnelUp()) {
            throw IllegalStateException("tunnel backend unavailable")
        }

        if (!APP_EXCLUDED_FROM_VPN || WdttTunnelManager.isApiOverlayActive()) {
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            MobileSyncLog.i("tunnel", "API direct ${tunnelApiBase()}")
            return block()
        }

        if (canUseMobileDirectTunnelApi()) {
            prepareMainVpnDirectApi()
            val direct = runCatching { block() }
            if (direct.isSuccess && !isTunnelBackendFailure(direct.getOrNull())) {
                MobileSyncLog.i("tunnel", "API mobile direct ${tunnelApiBase()}")
                return direct.getOrThrow()
            }
            MobileSyncLog.w(
                "tunnel",
                "API mobile direct failed → proxy/overlay: ${direct.exceptionOrNull()?.message}",
            )
            invalidateApiClient()
        }

        if (isOnMobileData()) {
            if (allowOverlayFallback) {
                useApiBase(tunnelApiBase())
                invalidateApiClient()
                MobileSyncLog.i("tunnel", "API overlay brief (LTE routine fallback)")
                return WdttTunnelManager.withApiOverlayBrief(block, allowDuringRampUp = true)
            }
            throw IllegalStateException("mobile excluded API outside overlay session")
        }

        var last: Throwable? = null
        repeat(4) { attempt ->
            if (prepareTunnelApiBaseLegacyProxy()) {
                MobileSyncLog.i("tunnel", "proxy attempt ${attempt + 1} url=${getServerUrl()}")
                val result = runCatching { block() }
                if (result.isSuccess && !isTunnelBackendFailure(result.getOrNull())) {
                    return result.getOrThrow()
                }
                last = result.exceptionOrNull()
                invalidateApiClient()
                val shouldRecycleProxy =
                    (result.isFailure && isTunnelUpstreamError(last?.message)) ||
                        (result.isSuccess && isTunnelBackendFailure(result.getOrNull()))
                if (shouldRecycleProxy && attempt < 3) {
                    runCatching { TunnelApiProxy.stopAndAwait() }
                }
            } else {
                MobileSyncLog.w("tunnel", "proxy not ready (attempt ${attempt + 1})")
            }
            if (attempt < 3) delay(750)
        }

        if (allowOverlayFallback) {
            useApiBase(tunnelApiBase())
            invalidateApiClient()
            MobileSyncLog.i("tunnel", "API overlay brief (Wi‑Fi fallback)")
            return WdttTunnelManager.withApiOverlayBrief(block, allowDuringRampUp = true)
        }

        throw last ?: IllegalStateException("tunnel backend unavailable")
    }

    private fun isTunnelBackendFailure(value: Any?): Boolean {
        if (value is Response<*>) return TunnelHttpPolicy.isTunnelBackendFailure(value)
        return false
    }

    private fun isTunnelUpstreamError(message: String?): Boolean =
        TunnelHttpPolicy.isTunnelUpstreamError(message)

    /** Public HTTPS Улья, затем standby-соты (если Улей режут по IP). */
    private fun publicApiBases(): List<String> {
        val out = linkedSetOf<String>()
        out.add("https://$DEFAULT_SERVER_HOST")
        out.add(getPublicServerUrl().trimEnd('/'))
        cachedStandbyApiBases().forEach { out.add(it) }
        return out.filter { it.isNotBlank() }.distinct()
    }

    private fun cachedStandbyApiBases(): List<String> {
        val fromPref = prefs.getString(PREF_STANDBY_API_URLS, null).orEmpty()
        val fromTheme = getCachedTheme()?.hive_standby_api_urls.orEmpty()
        val raw = if (fromPref.isNotBlank()) fromPref else fromTheme
        val parsed = raw.split(",").map { it.trim() }.filter { it.isNotBlank() }
        return (parsed + BAKED_STANDBY_API_URLS).distinct()
    }

    private fun tunnelApiBase(): String = "http://$WG_TUNNEL_GATEWAY:8000"

    /** TCP до 10.66.66.1:8000 реально проходит (не только флаг tunnelReady). */
    fun probeTunnelGateway(): Boolean {
        return try {
            val client = OkHttpClient.Builder()
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(2, TimeUnit.SECONDS)
                .callTimeout(3, TimeUnit.SECONDS)
                .build()
            val req = okhttp3.Request.Builder()
                .url("http://$WG_TUNNEL_GATEWAY:8000/health")
                .get()
                .build()
            client.newCall(req).execute().use { true }
        } catch (_: Exception) {
            false
        }
    }

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
            if (isOnMobileData() && TunnelApiProxy.isActive()) {
                TunnelApiProxy.stop()
            }
            useApiBase(tunnelApiBase())
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
                val res = getApi().getConfig(fp, getPreferredServer())
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
        runCatching { fetchOlcrtcConfig() }
            .onSuccess { cfg ->
                if (cfg != null) Log.i(TAG, "olcrtc-config OK after connect sync")
            }
            .onFailure { e -> Log.w(TAG, "olcrtc-config after connect: ${e.message}") }
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

    /** Main VPN (app inside tunnel): direct API через 10.66.66.1 без overlay. */
    fun prepareMainVpnDirectApi() {
        if (!isMainVpnTunnelUp()) return
        val target = tunnelApiBase()
        if (tunnelApiBaseUrl == target) return
        useApiBase(target)
        invalidateApiClient()
        Log.i(TAG, "API via main tunnel (direct): $target")
    }

    fun shouldUseTunnelApiProxy(): Boolean =
        !isOnMobileData() &&
            APP_EXCLUDED_FROM_VPN &&
            WdttTunnelManager.tunnelReady.value &&
            WdttTunnelManager.running.value &&
            !WdttTunnelManager.isBootstrapMode() &&
            TunnelApiProxy.isActive()

    private suspend fun prepareTunnelApiBase(): Boolean {
        if (!WdttTunnelManager.tunnelReady.value || !WdttTunnelManager.running.value) return false
        if (WdttTunnelManager.isBootstrapMode()) return false
        // mobileApiRoute: 10.66.66.0/24 в AllowedIPs — прямой HTTP без bind/proxy
        useApiBase(tunnelApiBase())
        invalidateApiClient()
        return true
    }

    private suspend fun prepareTunnelApiBaseLegacyProxy(): Boolean {
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
        MobileSyncLog.i("tunnel", "API via local proxy ${TunnelApiProxy.baseUrl()} mobile=${isOnMobileData()}")
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

    suspend fun ensureTunnelApiProxy(): Boolean =
        if (isOnMobileData()) false else prepareTunnelApiBaseLegacyProxy()

    /**
     * Основной VPN: без overlay (LTE API не через WG; отзыв — GETCONF/DTLS).
     * Bootstrap: overlay через withApiOverlay.
     */
    suspend fun <T> withTunnelApiWhenExcluded(block: suspend () -> T): T =
        withTunnelApiWhenExcludedInternal(block, allowDuringRampUp = false)

    fun isMainVpnTunnelUp(): Boolean =
        com.silent.vpn.service.SilentVpnService.isRunning &&
            com.silent.vpn.vpn.WdttTunnelManager.running.value &&
            com.silent.vpn.vpn.WdttTunnelManager.tunnelReady.value &&
            !com.silent.vpn.vpn.WdttTunnelManager.isBootstrapMode()

    /** API/sync через VPN — только когда воркеры подняты (не во время ramp-up). */
    fun isMainVpnApiReady(): Boolean =
        isMainVpnTunnelUp() &&
            com.silent.vpn.vpn.WdttTunnelManager.activeWorkers.value >= 1 &&
            !com.silent.vpn.vpn.WdttTunnelManager.isWorkerRampUpActive()

    /**
     * Main VPN tunnel API — только proxy/direct bind, без overlay.
     */
    suspend fun <T> withTunnelApiStrict(block: suspend () -> T): T {
        check(isMainVpnTunnelUp()) { "VPN tunnel not up" }
        return withTunnelBackendBlock(block = block)
    }

    /** Backend API для UI/ConfigSync — без overlay (overlay только для withUserBackendApi). */
    suspend fun <T> withBackendApi(block: suspend () -> T): T = withRoutineBackendApi(block = block)

    /**
     * OTA: LTE после initial sync — direct tunnel без overlay;
     * до sync — один overlay; Wi‑Fi — public или proxy с overlay fallback.
     */
    suspend fun <T> withOtaBackendApi(block: suspend () -> T): T {
        if (isOnMobileData() && APP_EXCLUDED_FROM_VPN && isMainVpnTunnelUp()) {
            if (canUseMobileDirectTunnelApi() || WdttTunnelManager.isApiOverlayActive()) {
                if (TunnelApiProxy.isActive()) {
                    TunnelApiProxy.stopAndAwait()
                }
                prepareMainVpnDirectApi()
                return block()
            }
            return WdttTunnelManager.withApiOverlayBrief(
                block = {
                    if (TunnelApiProxy.isActive()) {
                        TunnelApiProxy.stopAndAwait()
                    }
                    prepareMainVpnDirectApi()
                    block()
                },
                allowDuringRampUp = true,
                skipIntervalThrottle = true,
            )
        }
        return withRoutineBackendApi(allowOverlayFallback = true, block = block)
    }

    /** Долгая загрузка APK — tunnel direct/proxy без overlay. */
    suspend fun <T> withTunnelApiForUpdateDownload(block: suspend () -> T): T {
        if (!isMainVpnTunnelUp()) {
            Log.w(TAG, "withTunnelApiForUpdateDownload: tunnel not ready")
            error("VPN tunnel not ready for update download")
        }
        return withTunnelBackendBlock(allowOverlayFallback = false, block = block)
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
        standbyApiBasesFromTheme().forEach { out.add(it) }
        cachedStandbyApiBases().forEach { out.add(it) }
        out.add("https://${BootstrapVpnConfig.serverHost()}")
        out.add("https://$DEFAULT_SERVER_HOST")
        out.add(getPublicServerUrl())
        return out.filter { it.isNotBlank() }.toList()
    }

    private fun standbyApiBasesFromTheme(): List<String> {
        val raw = getCachedTheme()?.hive_standby_api_urls.orEmpty()
        if (raw.isBlank()) return emptyList()
        return raw.split(",").map { it.trim() }.filter { it.isNotBlank() }
    }

    fun getPublicServerUrl(): String {
        val raw = prefs.getString(PREF_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
        // Старый дефолт по IP: TLS к сертификату nip.io часто hang/fail на assign.
        if (raw.contains("132.243.234.162") && !raw.contains("nip.io")) {
            val fixed = DEFAULT_SERVER_URL
            prefs.edit().putString(PREF_SERVER_URL, fixed).apply()
            return fixed
        }
        return raw
    }

    fun resolveUpdateDownloadBase(preferredBase: String?): String =
        UpdateUrlResolver.resolveUpdateDownloadBase(otaUrlInput(preferredBase))

    fun needsOverlayForUpdateDownload(base: String): Boolean =
        needsTunnelApiOverlay() && UpdateUrlResolver.isTunnelApiBase(base)

    fun joinUpdateUrl(base: String, downloadPath: String): String =
        UpdateUrlResolver.joinUpdateUrl(base, downloadPath)

    fun shouldUseTunnelUpdateDownload(): Boolean =
        UpdateUrlResolver.shouldUseTunnelUpdateDownload(otaUrlInput())

    fun resolveUpdateDownloadUrl(info: UpdateCheckResponse): String? =
        UpdateUrlResolver.resolveUpdateDownloadUrl(
            otaUrlInput().copy(
                githubDownloadUrl = info.github_download_url,
                downloadUrl = info.download_url,
                tunnelDownloadPath = info.tunnel_download_url,
            ),
        )

    suspend fun <T> withUpdateDownloadRoute(block: suspend () -> T): T {
        if (!shouldUseTunnelUpdateDownload()) return block()
        if (!APP_EXCLUDED_FROM_VPN) {
            prepareMainVpnDirectApi()
            return block()
        }
        Log.i(TAG, "OTA download LTE overlay → http://$WG_TUNNEL_GATEWAY:8000")
        return com.silent.vpn.vpn.WdttTunnelManager.withApiOverlayBrief(
            block = {
                if (TunnelApiProxy.isActive()) {
                    TunnelApiProxy.stopAndAwait()
                }
                prepareMainVpnDirectApi()
                block()
            },
            allowDuringRampUp = true,
            skipIntervalThrottle = true,
        )
    }

    fun isPublicCdnUpdateUrl(url: String): Boolean {
        if (shouldUseTunnelUpdateDownload()) return false
        return url.contains("github.com", ignoreCase = true) ||
            url.startsWith("https://", ignoreCase = true)
    }

    fun buildDownloadClient(): OkHttpClient {
        val nipHost = DEFAULT_SERVER_HOST
        val tunnelGw = WG_TUNNEL_GATEWAY
        return OkHttpClient.Builder()
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor { chain ->
                var req = chain.request()
                val host = req.url.host
                // Host nip.io — только для public HTTPS по IP; tunnel 10.66.66.1 / localhost — как есть.
                if (host.matches(Regex("""\d+\.\d+\.\d+\.\d+""")) &&
                    host != tunnelGw &&
                    !host.startsWith("127.")
                ) {
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
        clearPendingPaymentLabel()
        _api = null
        _apiCacheKey = null
    }

    fun getPendingPaymentLabel(): String =
        prefs.getString(PREF_PENDING_PAYMENT_LABEL, "")?.trim().orEmpty()

    fun savePendingPaymentLabel(label: String) {
        val v = label.trim()
        if (v.isBlank()) {
            clearPendingPaymentLabel()
            return
        }
        prefs.edit().putString(PREF_PENDING_PAYMENT_LABEL, v).apply()
    }

    fun clearPendingPaymentLabel() {
        prefs.edit().remove(PREF_PENDING_PAYMENT_LABEL).apply()
    }

    fun saveCachedProfile(profile: UserProfile) {
        prefs.edit().putString(PREF_CACHED_PROFILE, Gson().toJson(profile)).apply()
    }

    /** Список устройств с /config не должен теряться, если live /me уже был. */
    private fun mergeNewerDeviceList(incoming: UserProfile) {
        val current = getCachedProfile() ?: run {
            saveCachedProfile(incoming)
            com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener?.onProfile(incoming)
            return
        }
        val changed = com.silent.vpn.policy.SessionsSyncPolicy.deviceListChanged(
            currentIds = current.devices.map { it.id }.toSet(),
            currentCount = current.devices_count,
            incomingIds = incoming.devices.map { it.id }.toSet(),
            incomingCount = incoming.devices_count,
        )
        if (!changed) return
        val merged = current.copy(
            devices = incoming.devices,
            devices_count = incoming.devices_count,
            connected_count = incoming.connected_count,
        )
        saveCachedProfile(merged)
        com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener?.onProfile(merged)
        Log.i(TAG, "client_sync merged devices ${current.devices_count}→${incoming.devices_count}")
    }

    fun isVpnAccessDenied(): Boolean = prefs.getBoolean(PREF_VPN_ACCESS_DENIED, false)

    fun setVpnAccessDenied(denied: Boolean) {
        prefs.edit().putBoolean(PREF_VPN_ACCESS_DENIED, denied).apply()
        if (denied) patchCachedVpnConfigProfileInactive()
    }

    /** Старый client_sync.profile с days_left не должен пережить отзыв. */
    private fun patchCachedVpnConfigProfileInactive() {
        val json = getCachedVpnConfigRaw() ?: return
        val cfg = runCatching { Gson().fromJson(json, VpnConfig::class.java) }.getOrNull() ?: return
        val sync = cfg.client_sync ?: return
        val profile = sync.profile ?: return
        if (!profile.subscription.is_active && profile.subscription.days_left <= 0) return
        val nextProfile = profile.copy(
            subscription = profile.subscription.copy(is_active = false, days_left = 0),
        )
        prefs.edit()
            .putString(PREF_CACHED_CONFIG, Gson().toJson(cfg.copy(client_sync = sync.copy(profile = nextProfile))))
            .apply()
        Log.i(TAG, "cached VPN client_sync profile marked inactive")
    }

    fun getCachedProfile(): UserProfile? {
        val json = prefs.getString(PREF_CACHED_PROFILE, null) ?: return null
        return runCatching { Gson().fromJson(json, UserProfile::class.java) }.getOrNull()
    }

    fun clearCachedProfile() {
        liveProfileAppliedAtMs = 0L
        prefs.edit()
            .remove(PREF_CACHED_PROFILE)
            .remove(PREF_VPN_ACCESS_DENIED)
            .apply()
    }

    fun saveCachedTheme(theme: ThemeData) {
        val urls = theme.hive_standby_api_urls.orEmpty().trim()
        prefs.edit()
            .putString(PREF_CACHED_THEME, Gson().toJson(theme))
            .apply {
                if (urls.isNotBlank()) putString(PREF_STANDBY_API_URLS, urls)
            }
            .apply()
    }

    fun getCachedTheme(): ThemeData? {
        val json = prefs.getString(PREF_CACHED_THEME, null) ?: return null
        return runCatching { Gson().fromJson(json, ThemeData::class.java) }.getOrNull()
    }

    fun saveCachedReferral(info: ReferralInfo) {
        prefs.edit().putString(PREF_CACHED_REFERRAL, Gson().toJson(info)).apply()
    }

    fun getCachedReferral(): ReferralInfo? {
        val json = prefs.getString(PREF_CACHED_REFERRAL, null) ?: return null
        return runCatching { Gson().fromJson(json, ReferralInfo::class.java) }.getOrNull()
    }

    /** Живой /me уже в UI — client_sync.profile не перетирает (после оплаты тумблер брал stale «нет»). */
    fun markLiveProfileApplied() {
        liveProfileAppliedAtMs = System.currentTimeMillis()
    }

    /** Данные с /vpn/config вместе с подпиской — без overlay HTTP после включения. */
    fun applyClientSync(bundle: ClientSyncBundle?, forceProfile: Boolean = false): Boolean {
        if (bundle == null) return false
        var applied = false
        bundle.profile?.let {
            val current = getCachedProfile()
            val wouldDowngradePaid =
                current != null &&
                    (current.is_admin || current.subscription.is_active) &&
                    !it.is_admin &&
                    !it.subscription.is_active
            when {
                !forceProfile && liveProfileAppliedAtMs > 0L -> {
                    mergeNewerDeviceList(it)
                    MobileSyncLog.i("clientSync", "keep live /me — merge devices if changed")
                }
                !forceProfile && wouldDowngradePaid -> {
                    mergeNewerDeviceList(it)
                    MobileSyncLog.i(
                        "clientSync",
                        "skip stale inactive client_sync profile — paid subscription already cached",
                    )
                }
                else -> {
                    saveCachedProfile(it)
                    if (it.is_admin || it.subscription.is_active) {
                        setVpnAccessDenied(false)
                        liveProfileAppliedAtMs = System.currentTimeMillis()
                    } else if (forceProfile) {
                        liveProfileAppliedAtMs = System.currentTimeMillis()
                    }
                    com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener?.onProfile(it)
                }
            }
            applied = true
        }
        bundle.theme?.let {
            saveCachedTheme(it)
            com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener?.onTheme(it)
            applied = true
        }
        bundle.referral?.let {
            saveCachedReferral(it)
            applied = true
        }
        bundle.hashes?.takeIf { it.isNotEmpty() }?.let { hashes ->
            runCatching {
                val items = hashes.mapIndexed { i, h ->
                    HashItemDto(
                        hash = h,
                        label = "Сервер ${i + 1}",
                        source = "server",
                        slot_index = i,
                        is_active = true,
                        status = "active",
                    )
                }
                saveHashItems(items)
                com.silent.vpn.sync.VpnDataSyncBridge.configSyncListener?.onHashesUpdated(
                    items,
                    applyToTunnel = false,
                )
                applied = true
            }
        }
        bundle.sync?.let { state ->
            if (state.hashes > 0) saveSyncHashesRev(state.hashes)
            if (state.theme > 0) saveSyncThemeRev(state.theme)
            if (state.profile > 0) saveSyncProfileRev(state.profile)
        }
        return applied
    }

    fun applyCachedClientSync(): Boolean {
        val json = getCachedVpnConfigRaw() ?: return false
        val bundle = runCatching {
            Gson().fromJson(json, VpnConfig::class.java)?.client_sync
        }.getOrNull()
        if (bundle == null) {
            MobileSyncLog.i("clientSync", "cached vpn config has no client_sync")
            return false
        }
        // Профиль UI только из живого /me — в кеше WG часто старый client_sync до оплаты.
        return applyClientSync(bundle.copy(profile = null))
    }

    fun getAppearanceMode(): String =
        prefs.getString(PREF_APPEARANCE_MODE, "light")?.takeIf { it == "dark" || it == "light" } ?: "light"

    fun setAppearanceMode(mode: String) {
        val normalized = if (mode == "dark") "dark" else "light"
        prefs.edit().putString(PREF_APPEARANCE_MODE, normalized).apply()
    }

    fun toggleAppearanceMode(): String {
        val next = if (getAppearanceMode() == "dark") "light" else "dark"
        setAppearanceMode(next)
        return next
    }

    fun getDnsPreset(): DnsPreset =
        DnsPreset.fromId(prefs.getString(PREF_DNS_PRESET, DnsPreset.DEFAULT.id))

    fun setDnsPreset(preset: DnsPreset) {
        prefs.edit().putString(PREF_DNS_PRESET, preset.id).apply()
    }

    fun getCustomDnsRaw(): String = prefs.getString(PREF_DNS_CUSTOM, "").orEmpty()

    /** Свой DNS: сохраняем нормализованный список, пресет переводим в CUSTOM. */
    fun setCustomDns(raw: String): String? {
        val servers = DnsPreset.sanitizeCustomServers(raw)
        prefs.edit()
            .putString(PREF_DNS_CUSTOM, servers.orEmpty())
            .apply()
        return servers
    }

    fun dnsDescription(): String = DnsSettings.describe(getDnsPreset(), getCustomDnsRaw())

    fun dnsMenuLabel(): String = DnsSettings.shortLabel(getDnsPreset(), getCustomDnsRaw())

    /** null — DNS остаётся тот, что прислал сервер (`wg_dns`). */
    fun dnsServersForVpn(): String? = DnsSettings.override(getDnsPreset(), getCustomDnsRaw())

    fun isLoggedIn() = getAccessToken() != null

    fun getDeviceFingerprint(): String {
        return prefs.getString(PREF_DEVICE_FP, null)
            ?: throw IllegalStateException("Session not started")
    }

    /** Человекочитаемое имя устройства для списка сессий (напр. «Samsung SM-G991B» / «Xiaomi TV»). */
    fun getDeviceDisplayName(): String =
        com.silent.vpn.util.DevicePlatform.getDeviceDisplayName(context)

    /** Тип устройства для API: `android` или `android_tv`. */
    fun getApiDeviceType(): String =
        com.silent.vpn.util.DevicePlatform.apiDeviceType(context)

    fun getOtaPlatform(): String = com.silent.vpn.util.DevicePlatform.OTA_PLATFORM

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

    private fun cachedConfigSlotPref(slot: String): String =
        "${PREF_CACHED_CONFIG}_${normalizePreferredServer(slot)}"

    fun cacheVpnConfigForSlot(slot: String, json: String) {
        val key = cachedConfigSlotPref(slot)
        prefs.edit().putString(key, json).apply()
    }

    fun getCachedVpnConfigForSlot(slot: String): String? =
        prefs.getString(cachedConfigSlotPref(slot), null)?.takeIf { it.isNotBlank() }

    private fun persistVpnConfigBySlot(json: String) {
        val cfg = runCatching { Gson().fromJson(json, VpnConfig::class.java) }.getOrNull() ?: return
        val fromSelected = slotFromSelectedServer(cfg.selected_server)
        val fromIp = BAKED_SERVER_IPS.keys.firstOrNull { vpnConfigIpMatchesPreferred(cfg.server_ip, it) }
        val slot = fromSelected ?: fromIp ?: return
        cacheVpnConfigForSlot(slot, json)
    }

    fun getExcludedPackages(): Set<String> =
        prefs.getString(PREF_EXCLUDED_APPS, "")?.split(",")?.filter { it.isNotBlank() }?.toSet() ?: emptySet()

    fun isExclusionsWhitelist(): Boolean = prefs.getBoolean(PREF_EXCLUSIONS_WHITELIST, false)

    fun saveExcludedApps(packages: Set<String>, whitelist: Boolean = false) {
        prefs.edit()
            .putString(PREF_EXCLUDED_APPS, packages.joinToString(","))
            .putBoolean(PREF_EXCLUSIONS_WHITELIST, whitelist)
            .apply()
    }

    /**
     * Смена ЧС↔БС.
     * ЧС — пустой выбор; БС — [packages] (обычно все приложения уже отмечены).
     */
    fun saveExceptionsMode(whitelist: Boolean, packages: Set<String> = emptySet()) {
        prefs.edit()
            .putString(PREF_EXCLUDED_APPS, if (whitelist) packages.joinToString(",") else "")
            .putBoolean(PREF_EXCLUSIONS_WHITELIST, whitelist)
            .apply()
    }

    fun getBypassRoutesRaw(): String =
        prefs.getString(PREF_BYPASS_ROUTES, "")?.trim().orEmpty()

    fun saveBypassRoutes(raw: String) {
        prefs.edit().putString(PREF_BYPASS_ROUTES, raw.trim()).apply()
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

    data class VkCredLaunchParams(
        val vkAuthMode: String,
        val captchaMode: String,
    )

    /**
     * Эфемерный каскад на сессию подключения (не в prefs):
     * 0 = базовый, 1 = авто-капча, 2 = ручная.
     * Go при Flood control не падает в legacy внутри процесса — хост перезапускает с n=9.
     */
    @Volatile
    private var sessionEscalateLevel = 0

    fun getVkCredStrategy(): String {
        return prefs.getString(PREF_VK_CRED_STRATEGY, VK_CRED_VKCALLS)?.let { stored ->
            when (stored) {
                VK_CRED_AUTO, VK_CRED_MANUAL -> stored
                else -> VK_CRED_VKCALLS
            }
        } ?: VK_CRED_VKCALLS
    }

    fun setVkCredStrategy(strategy: String) {
        val normalized = when (strategy) {
            VK_CRED_AUTO, VK_CRED_MANUAL -> strategy
            else -> VK_CRED_VKCALLS
        }
        prefs.edit().putString(PREF_VK_CRED_STRATEGY, normalized).apply()
    }

    fun getBypassFamily(): String {
        return BYPASS_FAMILY_WDTT
    }

    fun setBypassFamily(family: String) {
        prefs.edit().putString(PREF_BYPASS_FAMILY, BYPASS_FAMILY_WDTT).commit()
    }

    fun isOlcrtcBypass(): Boolean =
        false

    fun getPreferredServer(): String =
        normalizePreferredServer(prefs.getString(PREF_PREFERRED_SERVER, SERVER_MAIN))

    fun setPreferredServer(server: String) {
        val next = normalizePreferredServer(server)
        prefs.edit().putString(PREF_PREFERRED_SERVER, next).commit()
        val slotJson = getCachedVpnConfigForSlot(next)
        if (!slotJson.isNullOrBlank()) {
            prefs.edit()
                .putString(PREF_CACHED_CONFIG, slotJson)
                .putLong(PREF_CACHED_CONFIG_TS, System.currentTimeMillis())
                .commit()
        } else {
            clearCachedVpnConfig()
        }
    }

    fun rememberVpnServerIps(servers: List<VpnServerInfo>) {
        if (servers.isEmpty()) return
        val type = object : TypeToken<MutableMap<String, String>>() {}.type
        val current: MutableMap<String, String> = runCatching {
            Gson().fromJson<MutableMap<String, String>>(
                prefs.getString(PREF_SERVER_IPS, "{}"),
                type,
            )
        }.getOrNull() ?: mutableMapOf()
        for (item in servers) {
            val ip = item.public_ip?.trim().orEmpty()
            val key = item.key?.trim().orEmpty()
            if (ip.isNotBlank() && key.isNotBlank()) {
                current[normalizePreferredServer(key)] = ip
            }
        }
        prefs.edit().putString(PREF_SERVER_IPS, Gson().toJson(current)).apply()
    }

    fun expectedIpForPreferred(slot: String = getPreferredServer()): String? {
        val type = object : TypeToken<Map<String, String>>() {}.type
        val stored: Map<String, String> = runCatching {
            Gson().fromJson<Map<String, String>>(
                prefs.getString(PREF_SERVER_IPS, "{}"),
                type,
            )
        }.getOrNull() ?: emptyMap()
        return stored[slot]?.takeIf { it.isNotBlank() } ?: BAKED_SERVER_IPS[slot]
    }

    fun vpnConfigIpMatchesPreferred(serverIp: String, slot: String = getPreferredServer()): Boolean {
        val got = ipv4OrRaw(serverIp)
        if (got.isBlank()) return false
        val baked = BAKED_SERVER_IPS[slot]?.let { ipv4OrRaw(it) }
        val stored = expectedIpForPreferred(slot)?.let { ipv4OrRaw(it) }
        if (baked != null && got == baked) return true
        if (stored != null && got == stored) return true
        return false
    }

    private fun ipv4OrRaw(raw: String): String {
        val dashed = raw.trim().replace('-', '.')
        return IPV4_RE.find(dashed)?.value ?: dashed
    }

    suspend fun fetchVpnServers(): VpnServersResponse {
        val fp = getDeviceFingerprint()
        val res = getApi().getVpnServers(fp)
        if (!res.isSuccessful) {
            throw IllegalStateException("vpn servers HTTP ${res.code()}")
        }
        val body = res.body() ?: VpnServersResponse(getPreferredServer(), emptyList())
        rememberVpnServerIps(body.servers)
        return body
    }

    suspend fun selectVpnServer(serverKey: String): VpnServersResponse {
        val key = serverKey.trim().ifBlank { SERVER_MAIN }
        setPreferredServer(key)
        val res = getApi().selectVpnServer(
            PreferredServerRequest(
                device_fingerprint = getDeviceFingerprint(),
                preferred_server = key,
            ),
        )
        if (!res.isSuccessful) {
            throw IllegalStateException("vpn select server HTTP ${res.code()}")
        }
        val body = res.body() ?: VpnServersResponse(key, emptyList())
        runCatching { rememberVpnServerIps(body.servers) }
        return body
    }

    fun getOlcrtcProvider(): String {
        return when (val v = prefs.getString(PREF_OLCRTC_PROVIDER, OLCRTC_TELEMOST)) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> v
            else -> OLCRTC_TELEMOST // включая legacy jitsi
        }
    }

    fun setOlcrtcProvider(provider: String) {
        val normalized = when (provider) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
            else -> OLCRTC_TELEMOST
        }
        val prev = getOlcrtcProvider()
        prefs.edit().putString(PREF_OLCRTC_PROVIDER, normalized).commit()
        // Кеш per-provider — не стираем при смене (иначе «нет сессии» до конца prefetch).
        olcrtcConnectOverride = null
        lastFailedOlcrtcRoom = null
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.APPLY,
            "setProvider $prev → $normalized cacheTm=${getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST) != null} cacheWb=${getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM) != null}",
        )
    }

    /** Снимок живой olcrtc-сессии (не prefs после Apply). */
    @Volatile
    private var olcrtcActiveProvider: String? = null

    @Volatile
    private var olcrtcActiveRoomDbId: String? = null

    fun bindOlcrtcSession(provider: String, roomDbId: String?) {
        olcrtcActiveProvider = com.silent.vpn.policy.OlcrtcSessionPolicy.normalizeProvider(provider)
        olcrtcActiveRoomDbId = roomDbId?.trim()?.takeIf { it.isNotEmpty() }
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.SESS,
            "bind provider=$olcrtcActiveProvider roomDbId=$olcrtcActiveRoomDbId",
        )
    }

    fun clearOlcrtcSessionBind() {
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.SESS,
            "clear bind was provider=$olcrtcActiveProvider roomDbId=$olcrtcActiveRoomDbId",
        )
        olcrtcActiveProvider = null
        olcrtcActiveRoomDbId = null
    }

    fun sessionOlcrtcProvider(): String =
        com.silent.vpn.policy.OlcrtcSessionPolicy.resolveSessionProvider(
            olcrtcActiveProvider,
            getOlcrtcProvider(),
        )

    fun sessionOlcrtcRoomDbId(): String? = olcrtcActiveRoomDbId


    fun olcrtcProviderLabel(provider: String = getOlcrtcProvider()): String = when (provider) {
        OLCRTC_WBSTREAM -> "WB Stream"
        OLCRTC_TELEMOST -> "Яндекс Телемост"
        else -> "Яндекс Телемост"
    }

    fun bypassFamilyLabel(family: String = getBypassFamily()): String =
        if (family == BYPASS_FAMILY_OLCRTC2 || family == BYPASS_FAMILY_OLCRTC) {
            "olcrtc / ${olcrtcProviderLabel()}"
        } else {
            "VK"
        }

    private val PREF_OLCRTC_CACHE = "olcrtc_config_cache_v13" // legacy, только wipe
    private fun olcrtcCacheKey(provider: String): String =
        com.silent.vpn.policy.OlcrtcSessionPolicy.cacheKey(provider)
    private data class OlcrtcCacheEnvelope(
        val at: Long = 0L,
        val cfg: OlcrtcPublicConfig? = null,
    )

    /** One-shot после failure: retry обязан взять ЭТОТ cfg (не старый SharedPreferences). */
    @Volatile
    private var olcrtcConnectOverride: OlcrtcPublicConfig? = null

    /** Последняя room с early-fail — не стартовать её снова из soft/cache. */
    @Volatile
    private var lastFailedOlcrtcRoom: String? = null
    /** Anti-loop: не слать room-failure на один и тот же room слишком часто. */
    private val olcrtcFailureReportAtMs = java.util.concurrent.ConcurrentHashMap<String, Long>()
    private val OLCRTC_FAILURE_REPORT_DEBOUNCE_MS = 8_000L

    /** После leave слот dirty → connect делает assign (carrier), не blind preferCache. */
    private val olcrtcDirtyAfterLeave = java.util.concurrent.ConcurrentHashMap.newKeySet<String>()

    private fun markOlcrtcSlotDirty(provider: String) {
        olcrtcDirtyAfterLeave.add(
            when (provider) {
                OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
                else -> OLCRTC_TELEMOST
            },
        )
    }

    private fun clearOlcrtcSlotDirty(provider: String) {
        olcrtcDirtyAfterLeave.remove(
            when (provider) {
                OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
                else -> OLCRTC_TELEMOST
            },
        )
    }

    fun isOlcrtcSlotDirty(provider: String = getOlcrtcProvider()): Boolean =
        olcrtcDirtyAfterLeave.contains(
            when (provider) {
                OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
                else -> OLCRTC_TELEMOST
            },
        )

    fun getCachedOlcrtcConfig(): OlcrtcPublicConfig? =
        getCachedOlcrtcConfigForProvider(getOlcrtcProvider())

    /**
     * Кеш telemost и wbstream — **разные ключи**, не затирают друг друга.
     * Без fallback на legacy v13 (там был один слот → смена канала = «нет сессии»).
     */
    fun getCachedOlcrtcConfigForProvider(provider: String = getOlcrtcProvider()): OlcrtcPublicConfig? {
        val prov = when (provider) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
            else -> OLCRTC_TELEMOST
        }
        val raw = prefs.getString(olcrtcCacheKey(prov), null) ?: return null
        val cfg = runCatching {
            val env = Gson().fromJson(raw, OlcrtcCacheEnvelope::class.java)
            env?.cfg ?: Gson().fromJson(raw, OlcrtcPublicConfig::class.java)
        }.getOrNull()?.takeIf { it.enabled && it.crypto_key.length == 64 } ?: return null
        val room = cfg.providers[prov]?.room?.trim().orEmpty()
        return cfg.takeIf { room.isNotBlank() && cfg.providers[prov]?.enabled != false }
    }

    fun getOlcrtcCacheAgeMs(provider: String = getOlcrtcProvider()): Long? {
        val prov = when (provider) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
            else -> OLCRTC_TELEMOST
        }
        val raw = prefs.getString(olcrtcCacheKey(prov), null) ?: return null
        val at = runCatching {
            Gson().fromJson(raw, OlcrtcCacheEnvelope::class.java)?.at
        }.getOrNull() ?: return null
        if (at <= 0L) return null
        return (System.currentTimeMillis() - at).coerceAtLeast(0L)
    }

    fun shouldRefreshOlcrtcSlot(
        provider: String = getOlcrtcProvider(),
        force: Boolean = false,
        maxAgeMs: Long = 8 * 60 * 1000L,
    ): Boolean {
        val prov = when (provider) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
            else -> OLCRTC_TELEMOST
        }
        if (force) return true
        if (isOlcrtcSlotDirty(prov)) return true
        val cfg = getCachedOlcrtcConfigForProvider(prov) ?: return true
        val room = cfg.providers[prov]?.room?.trim().orEmpty()
        if (room.isBlank()) return true
        val age = getOlcrtcCacheAgeMs(prov) ?: return true
        return age >= maxAgeMs
    }

    private fun saveOlcrtcCache(cfg: OlcrtcPublicConfig, sync: Boolean = false, forProvider: String? = null) {
        if (!cfg.enabled || cfg.crypto_key.length != 64) return
        val wantKeys = com.silent.vpn.policy.OlcrtcSessionPolicy.isolateProviderKeysForCache(
            forProvider,
            cfg.providers.keys,
        )
        val ed = prefs.edit()
        var wrote = false
        for ((rawKey, slot) in cfg.providers) {
            val k = rawKey.trim().lowercase()
            if (k !in wantKeys) continue
            if (k != OLCRTC_TELEMOST && k != OLCRTC_WBSTREAM) continue
            if (slot.denied == true || !slot.enabled || slot.room.isBlank()) continue
            val isolated = cfg.copy(providers = mapOf(k to slot))
            val wrapped = OlcrtcCacheEnvelope(at = System.currentTimeMillis(), cfg = isolated)
            ed.putString(olcrtcCacheKey(k), Gson().toJson(wrapped))
            wrote = true
        }
        if (!wrote) return
        ed.remove(PREF_OLCRTC_CACHE)
        if (sync) ed.commit() else ed.apply()
        for ((rawKey, slot) in cfg.providers) {
            val k = rawKey.trim().lowercase()
            if (k !in wantKeys) continue
            if (k != OLCRTC_TELEMOST && k != OLCRTC_WBSTREAM) continue
            if (slot.denied == true || !slot.enabled || slot.room.isBlank()) continue
            clearOlcrtcSlotDirty(k)
        }
        val rooms = cfg.providers.entries
            .filter {
                val k = it.key.trim().lowercase()
                k in wantKeys && (k == OLCRTC_TELEMOST || k == OLCRTC_WBSTREAM)
            }
            .joinToString(",") { "${it.key}=${it.value.room.take(24)}" }
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.CACHE,
            "save isolated=$wantKeys slots=$rooms",
        )
    }

    private fun acceptOlcrtcConfig(
        body: OlcrtcPublicConfig?,
        syncCache: Boolean = false,
        forProvider: String? = null,
    ): OlcrtcPublicConfig? {
        if (body == null) return null
        val prov = when (val p = (forProvider ?: getOlcrtcProvider()).trim().lowercase()) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> p
            else -> getOlcrtcProvider()
        }
        val slot = body.providers[prov]
        if (!com.silent.vpn.policy.OlcrtcSessionPolicy.shouldAcceptAssign(
                enabled = body.enabled,
                cryptoKeyLen = body.crypto_key.length,
                providerEnabled = slot?.enabled,
                room = slot?.room,
                denied = slot?.denied,
                poolDenied = body.pool_denied,
            )
        ) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "accept REJECT provider=$prov enabled=${body.enabled} crypto=${body.crypto_key.length} denied=${slot?.denied} room=${slot?.room?.take(24)} poolDenied=${body.pool_denied}",
            )
            return null
        }
        saveOlcrtcCache(body, sync = syncCache, forProvider = prov)
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.CFG,
            "accept OK provider=$prov room=${slot?.room?.take(40)} roomDbId=${slot?.room_db_id}",
        )
        return body
    }

    /**
     * Как 1.0.160: preferCache=true (LTE) → сразу кеш; иначе сеть, кеш fallback.
     * После failure override всегда побеждает (новый room).
     */
    suspend fun resolveOlcrtcConfig(preferCache: Boolean = false): OlcrtcPublicConfig? {
        olcrtcConnectOverride?.let { override ->
            olcrtcConnectOverride = null
            Log.i(
                TAG,
                "olcrtc-config: override room=${override.providers[getOlcrtcProvider()]?.room?.take(24)}",
            )
            return override
        }
        val prov = getOlcrtcProvider()
        val cached = getCachedOlcrtcConfigForProvider(prov)
        if (preferCache && cached != null) {
            Log.i(
                TAG,
                "olcrtc-config: preferCache room=${cached.providers[prov]?.room?.take(24)}",
            )
            return cached
        }
        return fetchOlcrtcConfig() ?: cached
    }

    /**
 * Connect: dual-cache — есть слот → сразу; сеть только если кеша нет
 * (после login/sync). lastFailed room → reassign.
 */
suspend fun resolveOlcrtcConfigForConnect(): OlcrtcPublicConfig? {
        olcrtcConnectOverride?.let { override ->
            val room = override.providers[getOlcrtcProvider()]?.room?.trim().orEmpty()
            if (room.isNotBlank()) {
                olcrtcConnectOverride = null
                Log.i(
                    TAG,
                    "olcrtc-config: connect override room=${room.take(24)}",
                )
                return override
            }
            olcrtcConnectOverride = null
        }
        val prov = getOlcrtcProvider()
        val bad = lastFailedOlcrtcRoom
        val cached = getCachedOlcrtcConfigForProvider(prov)
        val cachedRoom = cached?.providers?.get(prov)?.room?.trim().orEmpty()
        if (cachedRoom.isNotBlank() && (bad == null || cachedRoom != bad)) {
            Log.i(TAG, "olcrtc-config: preferCache room=${cachedRoom.take(24)}")
            com.silent.vpn.util.OlcrtcDiag.i(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "preferCache provider=$prov room=${cachedRoom.take(24)}",
            )
            return cached
        }
        if (cachedRoom.isNotBlank() && bad != null && cachedRoom == bad) {
            Log.i(TAG, "olcrtc-config: skip lastFailed room=${cachedRoom.take(24)}")
            return reportOlcrtcRoomFailure("skip lastFailed room=$cachedRoom")
        }
        // Кеша нет — без длинного public fetch (до 120с hang на nip.io).
        // Connect → ensureOlcrtcConfigApi: короткий public → ephemeral VK (как login).
        com.silent.vpn.util.OlcrtcDiag.w(
            com.silent.vpn.util.OlcrtcDiag.CFG,
            "connect cache miss provider=$prov — defer to ensureOlcrtcConfigApi",
        )
        return null
    }

    fun markOlcrtcRoomConnected(room: String?) {
        val r = room?.trim().orEmpty()
        if (r.isNotBlank() && r == lastFailedOlcrtcRoom) {
            lastFailedOlcrtcRoom = null
        }
        clearOlcrtcSlotDirty(getOlcrtcProvider())
    }

    /** Уже внутри tunnel/overlay-сессии — только getApi(), без смены маршрута. */
    private suspend fun fetchOlcrtcConfigDirect(): OlcrtcPublicConfig? {
        val dt = runCatching { getApiDeviceType() }.getOrDefault("android")
        val fp = runCatching { getDeviceFingerprint() }.getOrElse { stableDeviceFingerprint() }
        val prov = getOlcrtcProvider()
        return try {
            val res = getApi().getOlcrtcConfig(dt, fp, prov)
            acceptOlcrtcConfig(if (res.isSuccessful) res.body() else null)
        } catch (_: Exception) {
            null
        }
    }

    /**
     * /olcrtc2-config: при живом VK-туннеле — через 10.66.66.1 (LTE / белые списки),
     * иначе публичный nip.io. Создание комнаты Playwright ~30–90с → длинный readTimeout.
     *
     * [forProvider] — явный провайдер (не трогает prefs). Нужно, чтобы прогреть
     * telemost и wbstream в разные слоты кеша без смены текущего канала.
     *
     * [publicConnectSec]/[publicReadSec] — для probe с Wi‑Fi (короткий miss → ephemeral),
     * не ждать 120с на мёртвом nip.io после переустановки.
     */
    suspend fun fetchOlcrtcConfig(
        forProvider: String? = null,
        publicConnectSec: Long = 30L,
        publicReadSec: Long = 120L,
    ): OlcrtcPublicConfig? {
        val dt = runCatching { getApiDeviceType() }.getOrDefault("android")
        val fp = runCatching { getDeviceFingerprint() }.getOrElse { stableDeviceFingerprint() }
        val prov = when (val p = (forProvider ?: getOlcrtcProvider()).trim().lowercase()) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> p
            else -> getOlcrtcProvider()
        }
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.CFG,
            "fetch start provider=$prov prefs=${getOlcrtcProvider()} session=${olcrtcActiveProvider} cache=${getCachedOlcrtcConfigForProvider(prov) != null}",
        )
        // assign создаёт Telemost на соте — клиент обязан ждать дольше обычного API.
        val olcrtcConnectSec = 30L
        val olcrtcReadSec = 120L

        suspend fun fetchOnce(api: SilentApi): OlcrtcPublicConfig? {
            val res = api.getOlcrtcConfig(dt, fp, prov)
            return acceptOlcrtcConfig(
                if (res.isSuccessful) res.body() else null,
                forProvider = prov,
            )
        }

        val tunnelReady =
            isMainVpnTunnelUp() ||
                (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value)

        if (tunnelReady) {
            if (VpnSessionState.initialOverlaySyncActive || WdttTunnelManager.isApiOverlayActive()) {
                runCatching {
                    prepareMainVpnDirectApi()
                    // overlay getApi() — короткий timeout; отдельный клиент на tunnel base
                    val api = buildApi(
                        "${tunnelApiBase().trimEnd('/')}/",
                        vpnNetwork = VpnNetworkHelper.getSilentVpnNetwork(context),
                        connectTimeoutSec = olcrtcConnectSec,
                        readTimeoutSec = olcrtcReadSec,
                    )
                    fetchOnce(api)
                }.getOrNull()?.let {
                    Log.i(TAG, "olcrtc-config OK via overlay tunnel provider=$prov")
                    return it
                }
            }
            runCatching {
                val api = buildApi(
                    "${tunnelApiBase().trimEnd('/')}/",
                    vpnNetwork = VpnNetworkHelper.getSilentVpnNetwork(context),
                    connectTimeoutSec = olcrtcConnectSec,
                    readTimeoutSec = olcrtcReadSec,
                )
                fetchOnce(api)
            }.getOrNull()?.let {
                Log.i(TAG, "olcrtc-config OK via tunnel API provider=$prov")
                return it
            }
            if (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value) {
                runCatching {
                    ensureBootstrapTunnelApi()
                    val api = buildApi(
                        "${tunnelApiBase().trimEnd('/')}/",
                        connectTimeoutSec = olcrtcConnectSec,
                        readTimeoutSec = olcrtcReadSec,
                    )
                    fetchOnce(api)
                }.getOrNull()?.let {
                    Log.i(TAG, "olcrtc-config OK via bootstrap tunnel provider=$prov")
                    return it
                }
            }
            Log.w(TAG, "olcrtc-config tunnel failed, skip public (whitelist / overwrite)")
            return getCachedOlcrtcConfigForProvider(prov)
        }

        if (VpnNetworkHelper.isOnMobileData(context)) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "public fetch SKIP LTE/БС provider=$prov — нужен tunnel/ephemeral",
            )
            return getCachedOlcrtcConfigForProvider(prov)
        }

        return try {
            val publicBase = getPublicServerUrl().trimEnd('/')
            // Prefer Wi‑Fi/Ethernet: firstOrNull часто берёт LTE при dual-stack → nip.io hang,
            // пока /users/me по default route (Wi‑Fi) жив.
            val net = runCatching {
                val cm = context.getSystemService(android.net.ConnectivityManager::class.java)
                    ?: return@runCatching null
                fun usable(n: android.net.Network): Boolean {
                    val caps = cm.getNetworkCapabilities(n) ?: return false
                    if (caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN)) return false
                    return caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
                }
                cm.allNetworks.firstOrNull { n ->
                    usable(n) &&
                        (
                            cm.getNetworkCapabilities(n)
                                ?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) == true ||
                                cm.getNetworkCapabilities(n)
                                    ?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_ETHERNET) == true
                            )
                } ?: cm.activeNetwork?.takeIf { usable(it) }
                    ?: cm.allNetworks.firstOrNull { usable(it) }
            }.getOrNull()
            com.silent.vpn.util.OlcrtcDiag.i(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "public fetch bind net=${net != null} base=$publicBase provider=$prov",
            )
            val api = buildApi(
                "$publicBase/",
                vpnNetwork = net,
                connectTimeoutSec = publicConnectSec.coerceIn(5L, 60L),
                readTimeoutSec = publicReadSec.coerceIn(8L, 180L),
            )
            fetchOnce(api) ?: getCachedOlcrtcConfigForProvider(prov).also {
                if (it == null) {
                    com.silent.vpn.util.OlcrtcDiag.w(
                        com.silent.vpn.util.OlcrtcDiag.CFG,
                        "public fetch empty provider=$prov (LTE без VK → нужен bootstrap)",
                    )
                }
            }
        } catch (e: Exception) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "public fetch FAIL provider=$prov err=${e.javaClass.simpleName}:${e.message?.take(80)}",
            )
            getCachedOlcrtcConfigForProvider(prov)
        }
    }

    /**
     * Только через 10.66.66.1 (bootstrap/main tunnel). Без public fallback.
     * Для ephemeral/LTE Apply — иначе ConnectException на nip.io затирает смысл bootstrap.
     */
    suspend fun fetchOlcrtcConfigTunnelOnly(forProvider: String? = null): OlcrtcPublicConfig? {
        val dt = runCatching { getApiDeviceType() }.getOrDefault("android")
        val fp = runCatching { getDeviceFingerprint() }.getOrElse { stableDeviceFingerprint() }
        val prov = when (val p = (forProvider ?: getOlcrtcProvider()).trim().lowercase()) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> p
            else -> getOlcrtcProvider()
        }
        val boot = WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value
        val main = isMainVpnTunnelUp()
        if (!boot && !main) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "tunnel-only SKIP no tunnel provider=$prov",
            )
            return null
        }
        if (boot) ensureBootstrapTunnelApi()
        else prepareMainVpnDirectApi()
        val base = tunnelApiBase().trimEnd('/') + "/"
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.CFG,
            "tunnel-only fetch provider=$prov base=$base boot=$boot",
        )
        return runCatching {
            val net = VpnNetworkHelper.getSilentVpnNetwork(context)
            val api = buildApi(
                base,
                vpnNetwork = net,
                connectTimeoutSec = 30L,
                readTimeoutSec = 120L,
            )
            val res = api.getOlcrtcConfig(dt, fp, prov)
            acceptOlcrtcConfig(
                if (res.isSuccessful) res.body() else null,
                forProvider = prov,
            )
        }.onFailure { e ->
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.CFG,
                "tunnel-only FAIL provider=$prov err=${e.javaClass.simpleName}:${e.message?.take(80)}",
            )
        }.getOrNull()
    }

    suspend fun prefetchOlcrtcConfig() {
        fetchOlcrtcConfig()
    }

    /**
     * Прогрев обоих слотов (как 1.0.160): при входе / Wi‑Fi без БС сохраняем TM и WB.
     * Выбранный — fetch если слота нет или room пуст; соседний — только если пуст.
     * Soft leave на сервере держит sticky → переключение = подставить кеш, без wipe.
     */
    suspend fun prefetchOlcrtcBothProviders(): Pair<Boolean, Boolean> {
        val selected = getOlcrtcProvider()
        suspend fun ensure(p: String): Boolean {
            val had = getCachedOlcrtcConfigForProvider(p) != null
            val roomOk = getCachedOlcrtcConfigForProvider(p)
                ?.providers?.get(p)?.room?.isNotBlank() == true
            // Не force-refresh живой слот: иначе leave+teardown цикл и «нет сессии».
            if (roomOk && !com.silent.vpn.policy.OlcrtcSessionPolicy.shouldForcePrefetch(p, selected)) {
                return true
            }
            if (roomOk && p == selected) {
                // Выбранный со свежим кешом — ок без сети (Apply / reconnect).
                return true
            }
            val cfg = runCatching { fetchOlcrtcConfig(p) }.getOrNull()
            val fetched = cfg?.providers?.get(p)?.room?.isNotBlank() == true
            return com.silent.vpn.policy.OlcrtcSessionPolicy.prefetchOk(
                force = !had,
                hadCacheBefore = had,
                fetchedRoomNonBlank = fetched,
                hasCacheAfter = getCachedOlcrtcConfigForProvider(p) != null,
            )
        }
        val tm = ensure(OLCRTC_TELEMOST)
        val wb = ensure(OLCRTC_WBSTREAM)
        Log.i(TAG, "olcrtc prefetch both telemost=$tm wbstream=$wb selected=$selected")
        com.silent.vpn.util.OlcrtcDiag.i(
            com.silent.vpn.util.OlcrtcDiag.CFG,
            "prefetchBoth selected=$selected tm=$tm wb=$wb roomTm=${getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST)?.providers?.get(OLCRTC_TELEMOST)?.room?.take(20)} roomWb=${getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM)?.providers?.get(OLCRTC_WBSTREAM)?.room?.take(20)}",
        )
        return tm to wb
    }

    suspend fun sendOlcrtcHeartbeat(
        online: Boolean = true,
        provider: String? = null,
        roomDbId: String? = null,
    ) {
        try {
            val prov = when (val p = (provider ?: getOlcrtcProvider()).trim().lowercase()) {
                OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> p
                else -> getOlcrtcProvider()
            }
            val cfg = getCachedOlcrtcConfigForProvider(prov) ?: getCachedOlcrtcConfig()
            val id = roomDbId?.trim().orEmpty().ifEmpty {
                cfg?.providers?.get(prov)?.room_db_id?.trim().orEmpty()
            }
            if (id.isEmpty()) return
            com.silent.vpn.util.OlcrtcDiag.i(
                com.silent.vpn.util.OlcrtcDiag.HB,
                "heartbeat online=$online provider=$prov roomDbId=$id",
            )
            val fp = getDeviceFingerprint()
            val dt = runCatching { getApiDeviceType() }.getOrDefault("android")
            val req = OlcrtcHeartbeatRequest(
                room_db_id = id,
                fingerprint = fp,
                provider = prov,
                device_type = dt,
                online = online,
            )
            // LTE + app disallow: nip.io с underlying режется whitelist.
            // VPN Network.bind для excluded app → EPERM. Рабочий путь: HTTP через
            // локальный SOCKS (peer → exit → API), sticky появляется в сессиях.
            // Важно: Socket только на IO — иначе NetworkOnMainThreadException → «CONNECT fail».
            if (withContext(Dispatchers.IO) {
                    postOlcrtcJsonViaSocks("api/vpn/olcrtc2-heartbeat", Gson().toJson(req))
                }
            ) {
                com.silent.vpn.util.OlcrtcDiag.i(
                    com.silent.vpn.util.OlcrtcDiag.HB,
                    "heartbeat OK via socks",
                )
                return
            }
            // online=true через Wi‑Fi при мёртвом SOCKS = зелёный вис (sticky жив, сайты нет).
            // Underlying оставляем только для leave/offline и когда SOCKS ещё не поднят.
            if (online && OlcrtcTunnelManager.tunnelReady.value) {
                com.silent.vpn.util.OlcrtcDiag.w(
                    com.silent.vpn.util.OlcrtcDiag.HB,
                    "heartbeat socks fail — skip underlying online (tunnel not healthy)",
                )
                return
            }
            val publicBase = getPublicServerUrl().trimEnd('/')
            val cm = context.getSystemService(android.net.ConnectivityManager::class.java)
            val vpnNet = VpnNetworkHelper.getSilentVpnNetwork(context)
            val underlying = cm?.allNetworks?.firstOrNull { n ->
                val caps = cm.getNetworkCapabilities(n) ?: return@firstOrNull false
                !caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN) &&
                    caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
            }
            val onMobile = VpnNetworkHelper.isOnMobileData(context)
            val attempts: List<Pair<android.net.Network?, String>> =
                if (onMobile) {
                    listOf(vpnNet to "vpn", underlying to "underlying", null to "default")
                } else {
                    listOf(underlying to "underlying", vpnNet to "vpn", null to "default")
                }
            var ok = false
            for ((net, tag) in attempts) {
                if (tag != "default" && net == null) continue
                val res = runCatching {
                    buildApi("$publicBase/", vpnNetwork = net, connectTimeoutSec = 10L)
                        .olcrtcHeartbeat(req)
                }.getOrNull()
                if (res != null && res.isSuccessful) {
                    com.silent.vpn.util.OlcrtcDiag.i(
                        com.silent.vpn.util.OlcrtcDiag.HB,
                        "heartbeat OK via $tag",
                    )
                    ok = true
                    break
                }
                com.silent.vpn.util.OlcrtcDiag.w(
                    com.silent.vpn.util.OlcrtcDiag.HB,
                    "heartbeat $tag fail code=${res?.code()} err=${res?.errorBody()?.string()?.take(80)}",
                )
            }
            if (!ok) {
                com.silent.vpn.util.OlcrtcDiag.w(
                    com.silent.vpn.util.OlcrtcDiag.HB,
                    "heartbeat all paths failed online=$online",
                )
            }
        } catch (_: Exception) {
        }
    }

    /**
     * HTTPS POST к public API через olcrtc SOCKS (peer exit).
     * Нужен на LTE: SilentVPN в disallow, underlying whitelist режет nip.io.
     * Вызывать только с Dispatchers.IO (blocking sockets).
     */
    private fun postOlcrtcJsonViaSocks(apiPath: String, jsonBody: String): Boolean {
        if (OlcrtcTunnelManager.activeSocksEndpoint() == null) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.HB,
                "socks skip — tunnel/SOCKS not ready",
            )
            return false
        }
        // Всегда nip.io: IP в CONNECT/SNI ломает nginx Host и часть SOCKS DNS.
        val host = DEFAULT_SERVER_HOST
        val port = 443
        val path = "/" + apiPath.trimStart('/')
        val tcp = OlcrtcTunnelManager.openSocksTcp(host, port) ?: run {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.HB,
                "socks CONNECT fail host=$host:$port",
            )
            // Underlying Wi‑Fi HB не лечит data plane — эскалация в TunnelManager.
            OlcrtcTunnelManager.noteSocksPathFail("connect")
            return false
        }
        return try {
            tcp.soTimeout = 15_000
            val ssl = TrustAllCerts.sslSocketFactory()
                .createSocket(tcp, host, port, true) as javax.net.ssl.SSLSocket
            ssl.soTimeout = 15_000
            ssl.startHandshake()
            try {
                val bodyBytes = jsonBody.toByteArray(Charsets.UTF_8)
                val token = getAccessToken()
                val hdr = StringBuilder()
                hdr.append("POST $path HTTP/1.1\r\n")
                hdr.append("Host: $host\r\n")
                hdr.append("Content-Type: application/json; charset=utf-8\r\n")
                hdr.append("Accept: application/json\r\n")
                hdr.append("Content-Length: ${bodyBytes.size}\r\n")
                hdr.append("Connection: close\r\n")
                if (!token.isNullOrBlank()) {
                    hdr.append("Authorization: Bearer $token\r\n")
                }
                hdr.append("\r\n")
                val out = ssl.getOutputStream()
                out.write(hdr.toString().toByteArray(Charsets.US_ASCII))
                out.write(bodyBytes)
                out.flush()
                val statusLine = ssl.getInputStream().bufferedReader(Charsets.US_ASCII).readLine()
                    ?: run {
                        OlcrtcTunnelManager.noteSocksPathFail("empty_status")
                        return false
                    }
                val code = statusLine.split(' ').getOrNull(1)?.toIntOrNull() ?: 0
                val ok = code in 200..299
                if (!ok) {
                    com.silent.vpn.util.OlcrtcDiag.w(
                        com.silent.vpn.util.OlcrtcDiag.HB,
                        "socks HTTP $code status=$statusLine",
                    )
                    OlcrtcTunnelManager.noteSocksPathFail("http_$code")
                } else {
                    OlcrtcTunnelManager.noteSocksPathOk()
                }
                ok
            } finally {
                runCatching { ssl.close() }
            }
        } catch (e: Exception) {
            runCatching { tcp.close() }
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.HB,
                "socks POST err=${e.javaClass.simpleName}:${e.message?.take(60)}",
            )
            OlcrtcTunnelManager.noteSocksPathFail("post_err")
            false
        }
    }

    /**
     * Leave: сервер снимает sticky (комната → warm); слот кеша НЕ чистим.
     * Соседний Telemost↔WB не трогаем (dual-cache).
     * Hard teardown только через reportOlcrtcRoomFailure.
     */
    suspend fun leaveOlcrtcRoom(provider: String? = null, roomDbId: String? = null) {
        val prov = when (val p = (provider ?: getOlcrtcProvider()).trim().lowercase()) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> p
            else -> getOlcrtcProvider()
        }
        val cfg = getCachedOlcrtcConfigForProvider(prov) ?: getCachedOlcrtcConfig()
        val pinnedId = roomDbId?.trim().orEmpty()
        com.silent.vpn.util.OlcrtcDiag.w(
            com.silent.vpn.util.OlcrtcDiag.LEAVE,
            "leave provider=$prov pinnedRoomDbId=${pinnedId.ifEmpty { "-" }} prefs=${getOlcrtcProvider()} session=${olcrtcActiveProvider} cacheBeforeTm=${getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST) != null} cacheBeforeWb=${getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM) != null}",
        )
        if (cfg == null && pinnedId.isEmpty()) {
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.LEAVE,
                "leave SKIP no cfg/room for $prov",
            )
            return
        }
        try {
            val fp = getDeviceFingerprint()
            val dt = runCatching { getApiDeviceType() }.getOrDefault("android")
            val publicBase = getPublicServerUrl().trimEnd('/')
            val net = runCatching {
                val cm = context.getSystemService(android.net.ConnectivityManager::class.java)
                cm?.allNetworks?.firstOrNull { n ->
                    val caps = cm.getNetworkCapabilities(n) ?: return@firstOrNull false
                    !caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN) &&
                        caps.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
                } ?: cm?.activeNetwork
            }.getOrNull()
            val api = buildApi("$publicBase/", vpnNetwork = net, connectTimeoutSec = 3L)
            suspend fun sendLeave(pName: String, id: String) {
                if (id.isEmpty()) return
                val leaveReq = OlcrtcHeartbeatRequest(
                    room_db_id = id,
                    fingerprint = fp,
                    provider = pName,
                    device_type = dt,
                    online = false,
                )
                if (withContext(Dispatchers.IO) {
                        postOlcrtcJsonViaSocks("api/vpn/olcrtc2-heartbeat", Gson().toJson(leaveReq))
                    }
                ) {
                    return
                }
                runCatching {
                    api.olcrtcHeartbeat(leaveReq)
                }.onFailure {
                    if (isMainVpnTunnelUp()) {
                        runCatching {
                            withUserBackendApi {
                                getApi().olcrtcHeartbeat(leaveReq)
                            }
                        }
                    }
                }
            }
            if (pinnedId.isNotEmpty()) {
                sendLeave(prov, pinnedId)
            } else if (cfg != null) {
                val id = cfg.providers[prov]?.room_db_id?.trim().orEmpty()
                sendLeave(prov, id)
            }
        } catch (_: Exception) {
        } finally {
            // Dual-cache 1.0.160: leave НЕ стирает слот; сервер только sticky.
            // Wipe только в reportOlcrtcRoomFailure (мёртвая room).
            olcrtcConnectOverride = null
            com.silent.vpn.util.OlcrtcDiag.w(
                com.silent.vpn.util.OlcrtcDiag.LEAVE,
                "leave DONE keepCache provider=$prov cacheTm=${getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST) != null} cacheWb=${getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM) != null}",
            )
        }
    }

    fun getLiveOlcrtcRoom(provider: String = getOlcrtcProvider()): String =
        getCachedOlcrtcConfigForProvider(provider)?.providers?.get(provider)?.room?.trim().orEmpty()

    fun clearOlcrtcCache() {
        prefs.edit()
            .remove(PREF_OLCRTC_CACHE)
            .remove(olcrtcCacheKey(OLCRTC_TELEMOST))
            .remove(olcrtcCacheKey(OLCRTC_WBSTREAM))
            .apply()
    }

    fun clearOlcrtcCacheForProvider(provider: String = getOlcrtcProvider()) {
        val prov = when (provider) {
            OLCRTC_WBSTREAM, OLCRTC_TELEMOST -> provider
            else -> OLCRTC_TELEMOST
        }
        prefs.edit().remove(olcrtcCacheKey(prov)).apply()
        com.silent.vpn.util.OlcrtcDiag.w(
            com.silent.vpn.util.OlcrtcDiag.CACHE,
            "wipe slot=$prov remainingTm=${getCachedOlcrtcConfigForProvider(OLCRTC_TELEMOST) != null} remainingWb=${getCachedOlcrtcConfigForProvider(OLCRTC_WBSTREAM) != null}",
        )
    }

    /** Peer dead / SOCKS timeout → сброс sticky + новый config. */
    suspend fun reportOlcrtcRoomFailure(detail: String = ""): OlcrtcPublicConfig? {
        // Важно: prefs могли смениться Apply (Telemost→WB) при живом старом туннеле.
        val prov = sessionOlcrtcProvider()
        val cfg = getCachedOlcrtcConfigForProvider(prov) ?: getCachedOlcrtcConfig()
        val roomDbId = olcrtcActiveRoomDbId
            ?: cfg?.providers?.get(prov)?.room_db_id.orEmpty()
        val oldRoom = cfg?.providers?.get(prov)?.room.orEmpty()
        val nowMs = System.currentTimeMillis()
        val lastReportMs = olcrtcFailureReportAtMs[prov] ?: 0L
        if (oldRoom.isNotBlank() && oldRoom == lastFailedOlcrtcRoom && nowMs - lastReportMs < OLCRTC_FAILURE_REPORT_DEBOUNCE_MS) {
            Log.w(
                TAG,
                "olcrtc roomFailure debounce provider=$prov room=${oldRoom.take(24)} dt=${nowMs - lastReportMs}ms",
            )
            return olcrtcConnectOverride ?: getCachedOlcrtcConfigForProvider(prov)
        }
        com.silent.vpn.util.OlcrtcDiag.e(
            com.silent.vpn.util.OlcrtcDiag.FAIL,
            "roomFailure provider=$prov room=${oldRoom.take(40)} roomDbId=$roomDbId prefs=${getOlcrtcProvider()} detail=${detail.take(80)}",
        )
        val req = OlcrtcRoomFailureRequest(
            room_db_id = roomDbId,
            fingerprint = getDeviceFingerprint(),
            provider = prov,
            device_type = runCatching { getApiDeviceType() }.getOrDefault("android"),
            detail = detail.ifBlank { "peer dead room=$oldRoom" },
        )
        try {
            val publicBase = getPublicServerUrl().trimEnd('/')
            val vpnNet = VpnNetworkHelper.getSilentVpnNetwork(context)
            val onMobile = VpnNetworkHelper.isOnMobileData(context)
            val socksOk = withContext(Dispatchers.IO) {
                postOlcrtcJsonViaSocks(
                    "api/vpn/olcrtc2-room-failure",
                    Gson().toJson(req),
                )
            }
            val sent = socksOk || if (onMobile && vpnNet != null) {
                runCatching {
                    buildApi("$publicBase/", vpnNetwork = vpnNet, connectTimeoutSec = 10L)
                        .olcrtcRoomFailure(req)
                }.isSuccess
            } else {
                false
            }
            if (!sent) {
                if (isMainVpnTunnelUp()) {
                    withUserBackendApi { getApi().olcrtcRoomFailure(req) }
                } else {
                    // На LTE/белых списках olcrtc2 API только через VPN path.
                    if (!onMobile) {
                        buildApi("$publicBase/", vpnNetwork = null, connectTimeoutSec = 8L)
                            .olcrtcRoomFailure(req)
                    }
                }
            }
        } catch (_: Exception) {
        }
        if (oldRoom.isNotBlank()) {
            lastFailedOlcrtcRoom = oldRoom
        }
        olcrtcFailureReportAtMs[prov] = nowMs
        // Кеш НЕ затираем: old room хранится как fallback until confirmed new room.
        // Старт на old room блокируется через lastFailedOlcrtcRoom.
        olcrtcConnectOverride = null
        // После tear на сервере warm может ещё не успеть — 2–3 попытки assign.
        // Сначала tunnel (если жив), иначе public; на LTE без tunnel public часто ConnectException.
        repeat(3) { attempt ->
            val next = when {
                isMainVpnTunnelUp() ||
                    (WdttTunnelManager.isBootstrapMode() && WdttTunnelManager.tunnelReady.value) ->
                    fetchOlcrtcConfigTunnelOnly(prov)
                else -> fetchOlcrtcConfig(prov)
            }
            val nextRoom = next?.providers?.get(prov)?.room?.trim().orEmpty()
            if (next != null && next.enabled && next.crypto_key.length == 64 && nextRoom.isNotBlank()) {
                if (badRoomSame(nextRoom, oldRoom)) {
                    Log.w(TAG, "olcrtc failure reassign got SAME dead room=${nextRoom.take(24)}")
                } else {
                    saveOlcrtcCache(next, sync = true, forProvider = prov)
                    olcrtcConnectOverride = next
                    if (nextRoom != oldRoom) {
                        lastFailedOlcrtcRoom = oldRoom
                    }
                    Log.i(
                        TAG,
                        "olcrtc failure reassign old=${oldRoom.take(20)} new=${nextRoom.take(20)} try=${attempt + 1}",
                    )
                    return next
                }
            }
            if (attempt < 2) {
                delay(900L * (attempt + 1))
            }
        }
        // НИКОГДА не возвращать старый cfg с мёртвой room (раньше → «новый канал» = тот же 404).
        Log.w(TAG, "olcrtc failure reassign: no fresh config (old=${oldRoom.take(24)})")
        return null
    }

    private fun badRoomSame(a: String, b: String): Boolean {
        val x = a.trim().lowercase()
        val y = b.trim().lowercase()
        return x.isNotBlank() && y.isNotBlank() && x == y
    }

    /** Сверить room с сервером; при смене — лог. Сеть мертва → кеш текущего провайдера. */
    suspend fun syncOlcrtcLiveChannel(): OlcrtcPublicConfig? {
        val prov = getOlcrtcProvider()
        val prev = getLiveOlcrtcRoom(prov)
        val cfg = fetchOlcrtcConfig() ?: return getCachedOlcrtcConfigForProvider(prov)
        val next = cfg.providers[prov]?.room?.trim().orEmpty()
        if (next.isNotEmpty() && next != prev) {
            val msg = if (prev.isEmpty()) {
                "канал: ${olcrtcProviderLabel(prov)} room=${next.take(48)}"
            } else {
                "канал сменился: ${olcrtcProviderLabel(prov)} ${prev.take(28)} → ${next.take(28)}"
            }
            com.silent.vpn.util.DebugLog.i("olcrtc", msg)
        }
        return if (next.isNotBlank()) cfg else getCachedOlcrtcConfigForProvider(prov)
    }

    fun getEffectiveVkCredStrategy(): String {
        val base = getVkCredStrategy()
        return when {
            sessionEscalateLevel >= 2 -> VK_CRED_MANUAL
            sessionEscalateLevel >= 1 -> if (base == VK_CRED_MANUAL) VK_CRED_MANUAL else VK_CRED_AUTO
            else -> base
        }
    }

    fun resetVkCredSessionEscalate() {
        sessionEscalateLevel = 0
    }

    /** vkcalls→auto→manual. false = уже manual. */
    fun escalateVkCredSession(): Boolean {
        val current = getEffectiveVkCredStrategy()
        if (current == VK_CRED_MANUAL) return false
        if (current == VK_CRED_AUTO) {
            sessionEscalateLevel = maxOf(sessionEscalateLevel, 2)
            return true
        }
        if (sessionEscalateLevel < 1) {
            sessionEscalateLevel = 1
            return true
        }
        if (sessionEscalateLevel < 2) {
            sessionEscalateLevel = 2
            return true
        }
        return false
    }

    fun resolveVkCredLaunchParams(): VkCredLaunchParams = when (getEffectiveVkCredStrategy()) {
        VK_CRED_AUTO -> VkCredLaunchParams(vkAuthMode = "legacy", captchaMode = "auto")
        VK_CRED_MANUAL -> VkCredLaunchParams(vkAuthMode = "legacy", captchaMode = "manual")
        else -> VkCredLaunchParams(vkAuthMode = "vkcalls", captchaMode = "auto")
    }

    /** Авто/ручная — запасной путь с капчей (не основной VK Calls). */
    fun isLegacyCaptchaStrategy(strategy: String = getEffectiveVkCredStrategy()): Boolean =
        strategy == VK_CRED_AUTO || strategy == VK_CRED_MANUAL

    fun vkCredStrategyLabel(strategy: String = getEffectiveVkCredStrategy()): String = when (strategy) {
        VK_CRED_AUTO -> "Авто капча"
        VK_CRED_MANUAL -> "Ручная"
        else -> "VKCalls"
    }

    /** @deprecated */
    fun getCaptchaBypassMode(): String = getVkCredStrategy()

    /** @deprecated */
    fun setCaptchaBypassMode(mode: String) = setVkCredStrategy(
        when (mode) {
            CAPTCHA_MODE_WV -> VK_CRED_AUTO
            CAPTCHA_MODE_RJS -> VK_CRED_MANUAL
            else -> VK_CRED_VKCALLS
        },
    )

    fun getTotalWorkers(activeHashCount: Int = getSavedHashItems().activeServerHashCount().coerceAtLeast(1)): Int {
        val capped = activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES)
        if (!BuildConfig.DEBUG) {
            return HashChannelHelper.normalizeTotalWorkers(
                HashChannelHelper.DEFAULT_TOTAL_WORKERS,
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
            HashChannelHelper.DEFAULT_TOTAL_WORKERS,
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
        if (isLegacyCaptchaStrategy()) {
            return HashChannelHelper.LEGACY_CAPTCHA_WORKERS
        }
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

    /** POST /disconnect — public HTTPS; на LTE excluded wdtt сам шлёт offline (S2S). */
    suspend fun notifyDisconnectBeforeTunnelStop(): Boolean {
        if (!isLoggedIn()) return false
        if (postDisconnectViaPublic()) return true
        if (isOnMobileData() && APP_EXCLUDED_FROM_VPN) {
            Log.i(TAG, "disconnect: skip tunnel API on LTE (wdtt S2S offline)")
            return false
        }
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

    /** Сохранить rev sync-state после успешного initial sync (внутри overlay-сессии). */
    suspend fun seedSyncRevisionsAfterTunnelSync() {
        runCatching {
            fetchSyncStateInternal()?.let { state ->
                saveSyncThemeRev(state.theme)
                saveSyncProfileRev(state.profile)
                state.hashes.takeIf { it > 0L }?.let { saveSyncHashesRev(it) }
            }
        }.onFailure { e -> Log.w(TAG, "seed sync rev: ${e.message}") }
    }

    /**
     * Полная синхронизация после включения главного VPN:
     * POST /connect → хеши → config → profile → theme. На LTE — overlay 10.66.66.1.
     */
    suspend fun syncAllViaTunnel(): Boolean = syncAllViaTunnelDetailed().ok

    suspend fun syncAllViaTunnelDetailed(): TunnelSyncResult = tunnelSyncMutex.withLock {
        val mobile = isOnMobileData()
        val excluded = APP_EXCLUDED_FROM_VPN
        val baseMeta = TunnelSyncResult(
            mobile = mobile,
            excludedApp = excluded,
            proxyActive = TunnelApiProxy.isActive(),
            apiUrl = getServerUrl(),
        )
        if (!isLoggedIn()) {
            return@withLock baseMeta.copy(error = "not logged in").also { it.logSummary("syncAll") }
        }
        prepareTunnelApiFromCachedConfig()
        invalidatePublicReachabilityCache()

        if (!mobile && postConnectViaPublic()) {
            return@withLock runCatching {
                val hashesOk = syncHashesAndConfigAfterConnect()
                val profileOk = syncProfileAndThemeAfterConnect()
                TunnelSyncResult(
                    ok = true,
                    connectOk = true,
                    hashesOk = hashesOk,
                    profileOk = profileOk,
                    mobile = false,
                    excludedApp = excluded,
                    apiUrl = getPublicServerUrl(),
                ).also { it.logSummary("syncAll") }
            }.getOrElse { e ->
                baseMeta.copy(error = e.message).also { it.logSummary("syncAll") }
            }
        }

        if (!isMainVpnTunnelUp()) {
            return@withLock baseMeta.copy(error = "main VPN tunnel not up").also { it.logSummary("syncAll") }
        }

        MobileSyncLog.i(
            "syncAll",
            "start excluded=$excluded mobile=$mobile proxy=${TunnelApiProxy.isActive()} wg=${WdttTunnelManager.lastWgAddress()}",
        )

        val overlayOn = WdttTunnelManager.isApiOverlayActive()
        val syncResult = runCatching {
            withTunnelBackendBlock(allowOverlayFallback = excluded && !mobile) {
                performTunnelSyncCycle(mobile, excluded, viaOverlay = overlayOn)
            }
        }.getOrElse { e ->
            MobileSyncLog.e("syncAll", "sync exception", e)
            baseMeta.copy(
                apiUrl = getServerUrl(),
                proxyActive = TunnelApiProxy.isActive(),
                error = e.message,
            )
        }

        syncResult.logSummary("syncAll")
        return@withLock syncResult
    }

    private suspend fun performTunnelSyncCycle(
        mobile: Boolean,
        excluded: Boolean,
        viaOverlay: Boolean = false,
    ): TunnelSyncResult {
        val url = getServerUrl()
        val channel = when {
            viaOverlay || WdttTunnelManager.isApiOverlayActive() -> "overlay"
            shouldUseTunnelApiProxy() -> "proxy"
            else -> "direct"
        }
        MobileSyncLog.i("syncAll", "cycle ($channel) API base=$url")
        val connectCode = postConnectOnlineViaTunnel()
        val online = connectCode in 200..299
        if (!online) {
            MobileSyncLog.w("syncAll", "POST /connect HTTP $connectCode via $url ($channel)")
        } else {
            MobileSyncLog.i("syncAll", "POST /connect OK via $url ($channel)")
        }
        val hashesOk = if (viaOverlay) {
            runCatching {
                syncHashesAndConfigAfterConnectDirect()
            }.getOrDefault(false)
        } else {
            syncHashesAndConfigAfterConnectDirect()
        }
        val profileOk = if (viaOverlay) {
            runCatching {
                syncProfileAndThemeAfterConnectDirect()
            }.getOrDefault(false)
        } else {
            syncProfileAndThemeAfterConnectDirect()
        }
        val subscriptionDenied = connectCode == 402
        val ok = profileOk || (online && hashesOk) || subscriptionDenied
        return TunnelSyncResult(
            ok = ok,
            connectOk = online,
            connectHttpCode = connectCode,
            subscriptionDenied = subscriptionDenied,
            hashesOk = hashesOk,
            profileOk = profileOk,
            mobile = mobile,
            excludedApp = excluded,
            proxyActive = TunnelApiProxy.isActive(),
            apiUrl = url,
            error = if (ok) null else "profile=$profileOk connect=$online hashes=$hashesOk",
        )
    }

    private suspend fun postConnectViaPublic(): Boolean {
        val body = ConnectRequest(
            getDeviceFingerprint(),
            getApiDeviceType(),
            preferred_server = getPreferredServer(),
        )
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

    private suspend fun postConnectOnlineViaTunnel(): Int {
        val result = runCatching {
            getApi().connect(
                ConnectRequest(
                    getDeviceFingerprint(),
                    getApiDeviceType(),
                    preferred_server = getPreferredServer(),
                ),
            )
        }
        val res = result.getOrNull()
        if (res == null) {
            MobileSyncLog.w(
                "connect",
                "POST /connect tunnel: ${result.exceptionOrNull()?.message} url=${getServerUrl()}",
            )
            return -1
        }
        if (res.isSuccessful) {
            MobileSyncLog.i("connect", "POST /connect OK tunnel url=${getServerUrl()}")
            return res.code()
        }
        val err = runCatching { res.errorBody()?.string()?.take(200) }.getOrNull()
        MobileSyncLog.w(
            "connect",
            "POST /connect tunnel HTTP ${res.code()} url=${getServerUrl()}${err?.let { " body=$it" } ?: ""}",
        )
        return res.code()
    }

    /** Профиль/theme — вызывать уже внутри withRoutineBackendApi (без повторной обёртки). */
    private suspend fun syncProfileAndThemeAfterConnectDirect(): Boolean {
        var ok = false
        val profileRes = getApi().getProfile()
        if (profileRes.isSuccessful) {
            profileRes.body()?.let { saveCachedProfile(it) }
            MobileSyncLog.i(
                "profile",
                "syncAll profile OK subActive=${profileRes.body()?.subscription?.is_active} url=${getServerUrl()}",
            )
            ok = true
        } else {
            MobileSyncLog.w("profile", "syncAll profile HTTP ${profileRes.code()} url=${getServerUrl()}")
        }
        val themeRes = getApi().getTheme()
        if (themeRes.isSuccessful) {
            themeRes.body()?.let { saveCachedTheme(it) }
            Log.i(TAG, "syncAll theme OK")
            ok = true
        }
        runCatching { fetchOlcrtcConfigDirect() }
            .onSuccess { cfg ->
                if (cfg != null) Log.i(TAG, "olcrtc-config OK with profile/theme tunnel")
            }
        return ok
    }

    private suspend fun syncHashesAndConfigAfterConnectDirect(): Boolean {
        if (!isLoggedIn()) return false
        var hashesOk = false
        runCatching {
            val items = fetchHashItemsOnce().getOrThrow()
            if (items.isNotEmpty()) {
                hashesOk = true
                Log.i(TAG, "syncHashes OK tunnel-direct (${items.size} items)")
            }
        }.onFailure { e -> Log.w(TAG, "syncHashes tunnel-direct: ${e.message}") }
        var configOk = false
        val fp = getDeviceFingerprint()
        runCatching {
            val res = getApi().getConfig(fp, getPreferredServer())
            if (res.isSuccessful) {
                res.body()?.let { cacheVpnConfig(Gson().toJson(it)) }
                configOk = true
                Log.i(TAG, "syncConfig OK device=${res.body()?.device_id?.take(8)}")
            }
        }.onFailure { e -> Log.w(TAG, "syncConfig: ${e.message}") }
        mergeSavedHashesIntoCachedConfig()
        runCatching { fetchOlcrtcConfigDirect() }
            .onSuccess { cfg ->
                if (cfg != null) Log.i(TAG, "olcrtc-config OK tunnel-direct")
            }
            .onFailure { e -> Log.w(TAG, "olcrtc-config tunnel-direct: ${e.message}") }
        return hashesOk || configOk
    }

    private suspend fun syncProfileAndThemeAfterConnect(): Boolean {
        return runCatching {
            withRoutineBackendApi {
                syncProfileAndThemeAfterConnectDirect()
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

    /** Тип сети для агента доступности: важно отличить сотового абонента от Wi‑Fi. */
    fun reportNetworkType(): String = when {
        isOnMobileData() -> "mobile"
        VpnNetworkHelper.hasUnderlyingInternet(context) -> "wifi"
        else -> "offline"
    }

    /** Оператор нужен, чтобы увидеть блокировку у одного оператора, а не у всех. */
    fun reportCarrier(): String = runCatching {
        if (!isOnMobileData()) return@runCatching ""
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        tm?.networkOperatorName?.trim().orEmpty().take(64)
    }.getOrDefault("")

    /**
     * Отправить репорт о срыве подключения. В отличие от хешей канал не ограничиваем
     * `allowsBackgroundConfigSync()`: смысл репорта именно в том, что связи не было,
     * а `withBackendApi` сам перебирает tunnel → public → соты.
     */
    suspend fun reportReachability(req: ReachabilityReportRequest): Result<Unit> {
        if (!isLoggedIn()) return Result.failure(IllegalStateException("not logged in"))
        return runCatching {
            withBackendApi {
                val res = getApi().reportReachability(req)
                if (!res.isSuccessful) {
                    throw Exception("reachability-report ${res.code()}")
                }
            }
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
        persistVpnConfigBySlot(json)
        runCatching {
            // Не тащить profile из WG-кеша: после оплаты там ещё «нет», а /me уже «да».
            Gson().fromJson(json, VpnConfig::class.java)?.client_sync?.let {
                applyClientSync(it.copy(profile = null))
            }
        }
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
        liveProfileAppliedAtMs = System.currentTimeMillis()
        if (body.is_admin || body.subscription.is_active) {
            setVpnAccessDenied(false)
        } else {
            setVpnAccessDenied(true)
        }
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
