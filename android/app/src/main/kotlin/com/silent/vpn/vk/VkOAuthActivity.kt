package com.silent.vpn.vk

import android.annotation.SuppressLint
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.launch

/**
 * VK OAuth в WebView (code flow). UA — обычный Chrome, не VKAndroidApp.
 */
class VkOAuthActivity : ComponentActivity() {

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val authUrl = intent.getStringExtra(EXTRA_AUTH_URL)
        if (authUrl.isNullOrBlank()) {
            setResult(Activity.RESULT_CANCELED)
            finish()
            return
        }

        val webView = WebView(this)
        setContentView(webView)
        webView.settings.javaScriptEnabled = true
        webView.settings.domStorageEnabled = true
        webView.settings.userAgentString = VkOAuthConfig.OAUTH_WEB_USER_AGENT
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                val url = request?.url?.toString() ?: return false
                return handleUrl(url)
            }

            @Deprecated("Deprecated in Java")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                if (url == null) return false
                return handleUrl(url)
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                handleUrl(url ?: return)
            }
        }
        DebugLog.i(TAG, "load OAuth (code flow)")
        webView.loadUrl(authUrl)
    }

    private fun handleUrl(url: String): Boolean {
        if (openExternalScheme(url)) return true

        if (url.contains("error=") || url.contains("error_description=")) {
            fail(parseOAuthError(url))
            return true
        }

        if (!url.contains("blank.html")) return false

        val uri = Uri.parse(url)
        val queryParams = parseParams(uri.encodedQuery)
        val fragmentParams = parseParams(uri.encodedFragment)

        queryParams["error_description"]?.let { fail(it); return true }
        fragmentParams["error_description"]?.let { fail(it); return true }

        fragmentParams["access_token"]?.takeIf { it.isNotBlank() }?.let { token ->
            val userId = fragmentParams["user_id"]?.toLongOrNull() ?: 0L
            succeed(token, userId)
            return true
        }

        queryParams["code"]?.takeIf { it.isNotBlank() }?.let { code ->
            lifecycleScope.launch {
                VkOAuthExchange.exchangeCode(code)
                    .onSuccess { succeed(it.accessToken, it.userId) }
                    .onFailure { fail(it.message ?: "Не удалось обменять code на token") }
            }
            return true
        }

        return false
    }

    private fun openExternalScheme(url: String): Boolean {
        val scheme = Uri.parse(url).scheme?.lowercase() ?: return false
        if (scheme !in EXTERNAL_SCHEMES) return false
        return try {
            val intent = when {
                url.startsWith("intent://") -> Intent.parseUri(url, Intent.URI_INTENT_SCHEME)
                else -> Intent(Intent.ACTION_VIEW, Uri.parse(url))
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (intent.resolveActivity(packageManager) != null) {
                startActivity(intent)
                DebugLog.i(TAG, "opened external scheme: $scheme")
            } else {
                fail("Установите приложение VK или выберите «Ввести вручную» на экране входа")
            }
            true
        } catch (e: ActivityNotFoundException) {
            fail("Не удалось открыть приложение VK. Выберите «Ввести вручную».")
            true
        } catch (e: Exception) {
            DebugLog.e(TAG, "openExternalScheme", e)
            fail("Не удалось открыть ссылку VK: ${e.message}")
            true
        }
    }

    private fun parseOAuthError(url: String): String {
        val uri = Uri.parse(url.replace("#", "?"))
        return uri.getQueryParameter("error_description")
            ?: uri.getQueryParameter("error")
            ?: "Ошибка VK OAuth"
    }

    private fun parseParams(raw: String?): Map<String, String> {
        if (raw.isNullOrBlank()) return emptyMap()
        return raw.split("&").mapNotNull {
            val p = it.split("=", limit = 2)
            if (p.size == 2) p[0] to Uri.decode(p[1]) else null
        }.toMap()
    }

    private fun succeed(token: String, userId: Long) {
        DebugLog.i(TAG, "OAuth ok userId=$userId")
        setResult(
            Activity.RESULT_OK,
            Intent()
                .putExtra(EXTRA_ACCESS_TOKEN, token)
                .putExtra(EXTRA_USER_ID, userId),
        )
        finish()
    }

    private fun fail(message: String) {
        DebugLog.e(TAG, "OAuth fail: $message")
        setResult(Activity.RESULT_CANCELED, Intent().putExtra(EXTRA_ERROR, message.replace("+", " ")))
        finish()
    }

    companion object {
        private const val TAG = "VkOAuthActivity"
        private val EXTERNAL_SCHEMES = setOf("vkontakte", "intent", "market")

        const val EXTRA_AUTH_URL = "auth_url"
        const val EXTRA_ACCESS_TOKEN = "access_token"
        const val EXTRA_USER_ID = "user_id"
        const val EXTRA_ERROR = "error"

        fun intent(context: Context, authUrl: String): Intent =
            Intent(context, VkOAuthActivity::class.java).putExtra(EXTRA_AUTH_URL, authUrl)
    }
}
