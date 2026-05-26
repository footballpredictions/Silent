package com.silent.vpn.data

import android.content.Context
import android.content.ClipboardManager
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SilentRepository @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        private const val TAG = "SilentRepository"
        const val DEFAULT_SERVER_URL = "https://132-243-234-162.nip.io"
        const val PREF_SERVER_URL = "server_url"
        const val PREF_ACCESS_TOKEN = "access_token"
        const val PREF_REFRESH_TOKEN = "refresh_token"
        const val PREF_DEVICE_FP = "device_fingerprint"
        const val PREF_VK_USER_ID = "vk_user_id"
        const val PREF_VK_ACCESS_TOKEN = "vk_access_token"
        const val PREF_BOOTSTRAP_HASH = "vk_bootstrap_hash"
        const val PREF_CACHED_CONFIG = "cached_vpn_config"
        const val PREF_CACHED_CONFIG_TS = "cached_vpn_config_ts"
        const val VK_APP_ID = 54610377L
        const val VK_GROUP_ID = 239092728L
    }

    private val prefs: SharedPreferences = createPrefs(context)

    private var _api: SilentApi? = null
    private var _baseUrl: String = ""

    init {
        ensureServerUrl()
    }

    private fun createPrefs(context: Context): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context, "silent_prefs", masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (e: Exception) {
            Log.w(TAG, "EncryptedSharedPreferences unavailable, using regular prefs", e)
            context.getSharedPreferences("silent_prefs", Context.MODE_PRIVATE)
        }
    }

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
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .addInterceptor { chain ->
                val token = getAccessToken()
                val req = if (token != null) {
                    chain.request().newBuilder()
                        .header("Authorization", "Bearer $token")
                        .build()
                } else chain.request()
                chain.proceed(req)
            }
            .hostnameVerifier { _, _ -> true }
            .sslSocketFactory(TrustAllCerts.sslSocketFactory(), TrustAllCerts.trustManager())
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(SilentApi::class.java)
    }

    fun getServerUrl(): String = prefs.getString(PREF_SERVER_URL, DEFAULT_SERVER_URL) ?: DEFAULT_SERVER_URL
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
        _api = null
    }
    fun isLoggedIn() = getAccessToken() != null

    fun getDeviceFingerprint(): String {
        return prefs.getString(PREF_DEVICE_FP, null)
            ?: throw IllegalStateException("Session not started")
    }

    /** New session id on each login — frees slot on logout. */
    fun startNewSession(): String {
        val fp = UUID.randomUUID().toString()
        prefs.edit().putString(PREF_DEVICE_FP, fp).apply()
        return fp
    }

    fun clearSessionFingerprint() {
        prefs.edit().remove(PREF_DEVICE_FP).apply()
    }

    fun hasSessionFingerprint(): Boolean = prefs.getString(PREF_DEVICE_FP, null) != null

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
