package com.silent.vpn.data

import android.content.Context
import android.content.ClipboardManager
import android.content.SharedPreferences
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

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
        const val PREF_VK_USER_ID = "vk_user_id"
        const val PREF_VK_ACCESS_TOKEN = "vk_access_token"
        const val PREF_BOOTSTRAP_HASH = "vk_bootstrap_hash"
        const val PREF_PRE_LOGIN_FP = "pre_login_fp"
        const val PREF_CACHED_CONFIG = "cached_vpn_config"
        const val PREF_CACHED_CONFIG_TS = "cached_vpn_config_ts"
        const val PREF_LAST_EMAIL = "last_email"
        const val PREF_SESSION_DEVICE_ID = "session_device_id"
        const val PREF_EXCLUDED_APPS = "excluded_apps"
        const val PREF_EXCLUSIONS_WHITELIST = "exclusions_whitelist"
        const val PREF_SAVED_HASH_ITEMS = "saved_hash_items"
        const val PREF_SAVED_HASH_ITEMS_TS = "saved_hash_items_ts"
        const val PREF_HASH_CHANNELS_PER_HASH = "hash_channels_per_hash"
        const val PREF_CACHED_PROFILE = "cached_profile_json"
        const val VK_APP_ID = 54610377L
        const val VK_GROUP_ID = 239092728L
        const val WG_TUNNEL_GATEWAY = "10.66.66.1"
    }

    private val prefs: SharedPreferences = createPrefs(context)

    private var _api: SilentApi? = null
    private var _baseUrl: String = ""
    /** Когда VPN поднят — API через адрес в туннеле (10.66.66.1), иначе nip.io недоступен в белых списках. */
    private var tunnelApiBaseUrl: String? = null

    init {
        ensureServerUrl()
    }

    private fun createPrefs(context: Context): SharedPreferences = SilentPrefs.open(context)

    fun getApi(): SilentApi {
        val url = getServerUrl()
        if (_api == null || _baseUrl != url) {
            _baseUrl = url.trimEnd('/') + "/"
            _api = buildApi(_baseUrl)
        }
        return _api!!
    }

    private fun buildApi(baseUrl: String): SilentApi {
        val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BASIC }
        val nipHost = DEFAULT_SERVER_HOST
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
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
            .connectTimeout(4, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SilentApi::class.java)
    }

    fun getServerUrl(): String {
        tunnelApiBaseUrl?.let { return it }
        return prefs.getString(PREF_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
    }

    /** Переключить API на WireGuard-шлюз (обычно 10.66.66.1) пока VPN активен. */
    fun setTunnelApiFromWgAddress(wgAddress: String?) {
        val gw = wgGatewayFromAddress(wgAddress)
        if (gw == null) {
            clearTunnelApiBase()
            return
        }
        useApiBase("http://$gw:8000")
        Log.i(TAG, "API via tunnel: http://$gw:8000")
    }

    fun clearTunnelApiBase() {
        if (tunnelApiBaseUrl != null) {
            tunnelApiBaseUrl = null
            _api = null
            Log.i(TAG, "API via public URL")
        }
    }

    /** WG API/nginx на сервере всегда 10.66.66.1 (не client_ip−1). */
    fun wgGatewayFromAddress(wgAddress: String?): String? {
        if (wgAddress.isNullOrBlank()) return WG_TUNNEL_GATEWAY
        val host = wgAddress.substringBefore('/').trim()
        if (!host.matches(Regex("""\d+\.\d+\.\d+\.\d+"""))) return null
        val parts = host.split('.').mapNotNull { it.toIntOrNull() }
        if (parts.size != 4) return null
        return "${parts[0]}.${parts[1]}.${parts[2]}.1"
    }

    fun apiBaseCandidates(wgAddress: String? = null): List<String> {
        val out = linkedSetOf<String>()
        wgGatewayFromAddress(wgAddress)?.let { gw ->
            out.add("http://$gw:8000")
            out.add("https://$gw")
        }
        out.add("https://${BootstrapVpnConfig.serverHost()}")
        out.add("https://$DEFAULT_SERVER_HOST")
        out.add(getPublicServerUrl())
        return out.filter { it.isNotBlank() }.toList()
    }

    fun getPublicServerUrl(): String =
        prefs.getString(PREF_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL

    /** Временно переключить base URL (для перебора кандидатов при входе). */
    fun useApiBase(baseUrl: String) {
        val normalized = baseUrl.trimEnd('/')
        if (tunnelApiBaseUrl != normalized) {
            tunnelApiBaseUrl = normalized
            _api = null
        }
    }
    fun setServerUrl(url: String) {
        prefs.edit().putString(PREF_SERVER_URL, url.trimEnd('/')).apply()
        _api = null
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
    }
    fun clearTokens() {
        prefs.edit().remove(PREF_ACCESS_TOKEN).remove(PREF_REFRESH_TOKEN).apply()
        clearCachedProfile()
        _api = null
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
    fun isLoggedIn() = getAccessToken() != null

    fun getDeviceFingerprint(): String {
        return prefs.getString(PREF_DEVICE_FP, null)
            ?: throw IllegalStateException("Session not started")
    }

    /** New session id on each login — frees slot on logout. */
    fun startNewSession(): String {
        clearCachedVpnConfig()
        clearSessionDeviceId()
        val fp = UUID.randomUUID().toString()
        prefs.edit().putString(PREF_DEVICE_FP, fp).apply()
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

    fun getLastEmail(): String? = prefs.getString(PREF_LAST_EMAIL, null)?.takeIf { it.isNotBlank() }

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

    fun saveBootstrapHash(hash: String?) {
        prefs.edit().apply {
            if (hash.isNullOrBlank()) remove(PREF_BOOTSTRAP_HASH) else putString(PREF_BOOTSTRAP_HASH, hash.trim())
        }.apply()
    }

    fun getBootstrapHash(): String? = prefs.getString(PREF_BOOTSTRAP_HASH, null)?.takeIf { it.isNotBlank() }

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
            Gson().fromJson<List<HashItemDto>>(json, type)
        }.getOrDefault(emptyList())
    }

    fun getSavedHashItemsUpdatedAt(): Long = prefs.getLong(PREF_SAVED_HASH_ITEMS_TS, 0L)

    fun getChannelsPerHash(): Int =
        HashChannelHelper.normalizeChannelsPerHash(
            prefs.getInt(PREF_HASH_CHANNELS_PER_HASH, HashChannelHelper.DEFAULT_CHANNELS_PER_HASH),
        )

    fun saveChannelsPerHash(value: Int) {
        prefs.edit()
            .putInt(PREF_HASH_CHANNELS_PER_HASH, HashChannelHelper.normalizeChannelsPerHash(value))
            .apply()
    }

    fun resolveVpnWorkerCount(vkHashCount: Int): Int {
        val savedActive = getSavedHashItems().activeServerHashCount()
        val activeHashes = maxOf(vkHashCount, savedActive, 1).coerceAtMost(HashChannelHelper.MAX_HASHES)
        return HashChannelHelper.computeWorkerCount(activeHashes, getChannelsPerHash())
    }

    fun clearSavedHashItems() {
        prefs.edit()
            .remove(PREF_SAVED_HASH_ITEMS)
            .remove(PREF_SAVED_HASH_ITEMS_TS)
            .apply()
    }

    suspend fun fetchAndSaveHashItems(): Result<List<HashItemDto>> {
        return runCatching {
            val res = getApi().getVpnHashes()
            if (!res.isSuccessful) {
                error(res.errorBody()?.string()?.take(200) ?: "HTTP ${res.code()}")
            }
            val items = res.body()!!.toHashItems()
            if (items.isNotEmpty()) saveHashItems(items)
            items
        }
    }

    /** Stable fingerprint for bootstrap VPN before Silent login. */
    fun getOrCreatePreLoginFingerprint(): String {
        val existing = prefs.getString(PREF_PRE_LOGIN_FP, null)?.takeIf { it.isNotBlank() }
        if (existing != null) return existing
        val fp = UUID.randomUUID().toString()
        prefs.edit().putString(PREF_PRE_LOGIN_FP, fp).apply()
        return fp
    }

    fun cacheVpnConfig(json: String) {
        prefs.edit()
            .putString(PREF_CACHED_CONFIG, json)
            .putLong(PREF_CACHED_CONFIG_TS, System.currentTimeMillis())
            .apply()
    }

    fun getCachedVpnConfig(): String? {
        val ts = prefs.getLong(PREF_CACHED_CONFIG_TS, 0L)
        if (System.currentTimeMillis() - ts > 7 * 24 * 60 * 60 * 1000L) return null
        return prefs.getString(PREF_CACHED_CONFIG, null)
    }

    fun getClipboardText(): String? {
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager ?: return null
        val clip = cm.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        return clip.getItemAt(0).coerceToText(context)?.toString()
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
