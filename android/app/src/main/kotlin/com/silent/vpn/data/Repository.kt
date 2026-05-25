package com.silent.vpn.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
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
        const val PREF_SERVER_URL = "server_url"
        const val PREF_ACCESS_TOKEN = "access_token"
        const val PREF_REFRESH_TOKEN = "refresh_token"
        const val PREF_DEVICE_FP = "device_fingerprint"
    }

    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs: SharedPreferences = EncryptedSharedPreferences.create(
        context, "silent_prefs", masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    private var _api: SilentApi? = null
    private var _baseUrl: String = ""

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
            // Accept self-signed certs (for IP-only TLS)
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

    fun getServerUrl(): String = prefs.getString(PREF_SERVER_URL, "") ?: ""
    fun setServerUrl(url: String) = prefs.edit().putString(PREF_SERVER_URL, url.trimEnd('/')).apply()
    fun isServerConfigured() = getServerUrl().isNotEmpty()

    fun getAccessToken(): String? = prefs.getString(PREF_ACCESS_TOKEN, null)
    fun getRefreshToken(): String? = prefs.getString(PREF_REFRESH_TOKEN, null)
    fun saveTokens(access: String, refresh: String) {
        prefs.edit()
            .putString(PREF_ACCESS_TOKEN, access)
            .putString(PREF_REFRESH_TOKEN, refresh)
            .apply()
        _api = null // Force rebuild with new token
    }
    fun clearTokens() {
        prefs.edit().remove(PREF_ACCESS_TOKEN).remove(PREF_REFRESH_TOKEN).apply()
        _api = null
    }
    fun isLoggedIn() = getAccessToken() != null

    fun getDeviceFingerprint(): String {
        var fp = prefs.getString(PREF_DEVICE_FP, null)
        if (fp == null) {
            fp = UUID.randomUUID().toString()
            prefs.edit().putString(PREF_DEVICE_FP, fp).apply()
        }
        return fp
    }
}

// Trust all certs helper (for self-signed IP certificates)
object TrustAllCerts {
    private val trustAll = arrayOf<javax.net.ssl.TrustManager>(
        object : javax.net.ssl.X509TrustManager {
            override fun checkClientTrusted(c: Array<java.security.cert.X509Certificate>, a: String) {}
            override fun checkServerTrusted(c: Array<java.security.cert.X509Certificate>, a: String) {}
            override fun getAcceptedIssuers(): Array<java.security.cert.X509Certificate> = arrayOf()
        }
    )

    fun sslSocketFactory(): javax.net.ssl.SSLSocketFactory {
        val sslContext = javax.net.ssl.SSLContext.getInstance("SSL")
        sslContext.init(null, trustAll, java.security.SecureRandom())
        return sslContext.socketFactory
    }

    fun trustManager() = trustAll[0] as javax.net.ssl.X509TrustManager
}
