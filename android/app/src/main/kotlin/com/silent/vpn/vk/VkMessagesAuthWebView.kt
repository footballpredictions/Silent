package com.silent.vpn.vk

import android.annotation.SuppressLint
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import com.silent.vpn.data.SilentRepository
import java.net.URLEncoder

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun VkMessagesAuthWebView(
    authUrl: String?,
    redirectPrefix: String,
    onToken: (String) -> Unit,
    onError: (String) -> Unit,
    onCancel: () -> Unit,
) {
    val startUrl = authUrl ?: run {
        val redirect = URLEncoder.encode(
            "${SilentRepository.DEFAULT_SERVER_URL.trimEnd('/')}/api/auth/vk/messages-callback",
            "UTF-8",
        )
        "https://oauth.vk.ru/authorize?client_id=${SilentRepository.VK_APP_ID}" +
            "&display=mobile&redirect_uri=$redirect" +
            "&scope=messages,offline&response_type=token&v=5.199&revoke=1"
    }

    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            WebView(ctx).apply {
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webViewClient = object : WebViewClient() {
                    private fun handleUrl(raw: String?): Boolean {
                        val url = raw ?: return false
                        if (url.contains("error=")) {
                            val uri = Uri.parse(url.replace("#", "?"))
                            val desc = uri.getQueryParameter("error_description")
                                ?: uri.getQueryParameter("error") ?: "Ошибка VK"
                            onError(desc.replace("+", " "))
                            return true
                        }
                        if (!url.startsWith(redirectPrefix) && !url.contains("access_token=")) {
                            return false
                        }
                        val token = Regex("access_token=([^&#]+)").find(url)?.groupValues?.get(1)
                        if (!token.isNullOrBlank()) {
                            onToken(token)
                            return true
                        }
                        return false
                    }

                    override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean {
                        return handleUrl(request?.url?.toString())
                    }

                    @Deprecated("Deprecated in Java")
                    override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean {
                        return handleUrl(url)
                    }

                    override fun onPageFinished(view: WebView?, url: String?) {
                        handleUrl(url)
                    }
                }
                loadUrl(startUrl)
            }
        },
    )
}
