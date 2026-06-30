package com.silent.vpn.vpn.captcha

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import kotlin.random.Random

/**
 * Невидимая Activity с WebView в иерархии окна — без неё Chromium на Android
 * не загружает id.vk.ru/captcha (orphan WebView с measure/layout не рендерится).
 * Аналог PC: BrowserWindow showInactive + opacity=0.
 */
class AutoCaptchaActivity : Activity() {

    private val mainHandler = Handler(Looper.getMainLooper())
    private var networkRetries = 0
    private var webView: WebView? = null
    private var postClickSliderWatcher: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        CaptchaWebViewManager.activeAutoActivity = this

        val redirectUri = intent.getStringExtra(EXTRA_REDIRECT_URI)
        if (redirectUri.isNullOrBlank()) {
            finishWithError("missing redirectUri")
            return
        }

        window.apply {
            setBackgroundDrawableResource(android.R.color.transparent)
            addFlags(
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            )
            attributes = attributes.apply {
                alpha = 0.01f
                width = WindowManager.LayoutParams.MATCH_PARENT
                height = WindowManager.LayoutParams.MATCH_PARENT
            }
        }

        val wv = createWebView(redirectUri)
        webView = wv
        setContentView(
            FrameLayout(this).apply {
                addView(
                    wv,
                    FrameLayout.LayoutParams(
                        FrameLayout.LayoutParams.MATCH_PARENT,
                        FrameLayout.LayoutParams.MATCH_PARENT,
                    ),
                )
            },
        )
        wv.onResume()
        wv.resumeTimers()
        wv.evaluateJavascript(INTERCEPTOR_JS, null)
        wv.loadUrl(redirectUri)
    }

    override fun onDestroy() {
        postClickSliderWatcher?.let { mainHandler.removeCallbacks(it) }
        webView?.let { destroyWebView(it) }
        webView = null
        if (CaptchaWebViewManager.activeAutoActivity === this) {
            CaptchaWebViewManager.abortAutoIfPending("activity destroyed")
            CaptchaWebViewManager.activeAutoActivity = null
        }
        super.onDestroy()
    }

    fun cancelSolve() {
        finishWithError(CancellationReason.SUPERSEDED)
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(redirectUri: String): WebView {
        val vw = VIEWPORT_WIDTHS[Random.Default.nextInt(VIEWPORT_WIDTHS.size)]
        val vh = VIEWPORT_HEIGHTS[Random.Default.nextInt(VIEWPORT_HEIGHTS.size)]
        val chromeBuild = CHROME_BUILDS[Random.Default.nextInt(CHROME_BUILDS.size)]
        val ua =
            "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/$chromeBuild Mobile Safari/537.36"

        Log.d(TAG, "Fingerprint: ${vw}x${vh}, Chrome/$chromeBuild")

        return WebView(this).apply {
            settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                databaseEnabled = true
                mediaPlaybackRequiresUserGesture = false
                loadWithOverviewMode = true
                useWideViewPort = true
                blockNetworkLoads = false
                cacheMode = android.webkit.WebSettings.LOAD_NO_CACHE
                userAgentString = ua
            }

            addJavascriptInterface(CaptchaJSBridge(), "WdttCaptcha")

            webViewClient = object : WebViewClient() {
                override fun onPageStarted(view: WebView, url: String?, favicon: android.graphics.Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    view.evaluateJavascript(INTERCEPTOR_JS, null)
                }

                override fun onReceivedError(
                    view: WebView,
                    request: WebResourceRequest?,
                    error: android.webkit.WebResourceError?,
                ) {
                    if (request?.isForMainFrame != true) return
                    val code = error?.errorCode ?: return
                    if ((code == -21 || code == ERROR_CONNECT || code == ERROR_HOST_LOOKUP) &&
                        networkRetries < 4
                    ) {
                        networkRetries++
                        Log.w(TAG, "Load error $code — retry $networkRetries/4")
                        mainHandler.postDelayed(
                            { if (!isFinishing) view.loadUrl(redirectUri) },
                            1200L + networkRetries * 1000L,
                        )
                        return
                    }
                    finishWithError("${error.description} ($code)")
                }

                override fun onPageFinished(view: WebView, url: String?) {
                    super.onPageFinished(view, url)
                    val isCaptchaPage = url?.let {
                        it.contains("not_robot_captcha") ||
                            it.contains("id.vk.ru/captcha") ||
                            it.contains("not_robot")
                    } ?: false
                    if (!isCaptchaPage || isFinishing) return
                    Log.d(TAG, "Страница капчи загружена")
                    view.evaluateJavascript(INTERCEPTOR_JS, null)
                    scheduleClickAttempts(view)
                }

                override fun onReceivedSslError(
                    view: WebView,
                    handler: android.webkit.SslErrorHandler,
                    error: android.net.http.SslError,
                ) {
                    val url = error.url ?: ""
                    if (url.contains("vk.ru") || url.contains("vk.com") || url.contains("okcdn.ru")) {
                        handler.proceed()
                    } else {
                        handler.cancel()
                    }
                }
            }

            webChromeClient = WebChromeClient()
        }
    }

    private fun scheduleClickAttempts(wv: WebView) {
        val delays = longArrayOf(
            1500L + Random.Default.nextLong(0, 800),
            4000L, 8000L, 13000L, 20000L,
        )
        for (delay in delays) {
            mainHandler.postDelayed({
                if (!isFinishing && webView === wv) {
                    tryClickCheckbox(wv)
                }
            }, delay)
        }
    }

    private fun tryClickCheckbox(wv: WebView) {
        if (isFinishing || webView !== wv) return

        val findLabelJS = """
            (function() {
                var slider = document.querySelector(
                    '[class*="SliderCaptcha"], [class*="Kaleidoscope"], ' +
                    '.vkc__SliderCaptcha-module__description, ' +
                    '.vkc__KaleidoscopeScreen-module__captchaId'
                );
                if (slider) return '${CaptchaWebViewManager.ERROR_SLIDER_DETECTED}';

                var el = document.querySelector('label.vkc__Checkbox-module__Checkbox');
                if (!el) el = document.querySelector('label[for="not-robot-captcha-checkbox"]');
                if (!el) el = document.getElementById('not-robot-captcha-checkbox');
                if (!el) return 'not_found';

                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                if (rect.width < 5 || rect.height < 5 ||
                    style.display === 'none' || style.visibility === 'hidden') {
                    return 'not_found';
                }
                return rect.left + ',' + rect.top + ',' + rect.width + ',' + rect.height;
            })();
        """.trimIndent()

        wv.evaluateJavascript(findLabelJS) { rawValue ->
            if (isFinishing || webView !== wv) return@evaluateJavascript
            val result = rawValue?.replace("\"", "") ?: ""

            if (result == CaptchaWebViewManager.ERROR_SLIDER_DETECTED) {
                finishWithSlider()
                return@evaluateJavascript
            }

            if (result == "not_found" || result.split(",").size < 4) {
                val jsClick = """
                    (function() {
                        var el = document.querySelector('label.vkc__Checkbox-module__Checkbox');
                        if (!el) el = document.getElementById('not-robot-captcha-checkbox');
                        if (el) { el.click(); return 'clicked'; }
                        return 'nothing';
                    })();
                """.trimIndent()
                wv.evaluateJavascript(jsClick) { clickResult ->
                    if ((clickResult ?: "").replace("\"", "") == "clicked") {
                        startPostClickSliderWatcher(wv)
                    }
                }
                return@evaluateJavascript
            }

            val parts = result.split(",")
            val left = parts[0].toFloatOrNull() ?: return@evaluateJavascript
            val top = parts[1].toFloatOrNull() ?: return@evaluateJavascript
            val width = parts[2].toFloatOrNull() ?: return@evaluateJavascript
            val height = parts[3].toFloatOrNull() ?: return@evaluateJavascript
            val randX = left + width * (0.15f + Random.Default.nextFloat() * 0.7f)
            val randY = top + height * (0.25f + Random.Default.nextFloat() * 0.5f)

            mainHandler.postDelayed({
                if (!isFinishing && webView === wv) {
                    simulateHumanTouch(wv, randX, randY)
                    startPostClickSliderWatcher(wv)
                }
            }, 420L + Random.Default.nextLong(0, 260))
        }
    }

    private fun startPostClickSliderWatcher(wv: WebView) {
        postClickSliderWatcher?.let { mainHandler.removeCallbacks(it) }
        var attemptsLeft = 14
        val watcher = object : Runnable {
            override fun run() {
                if (isFinishing || webView !== wv) return
                val detectSliderJS = """
                    (function() {
                        var slider = document.querySelector(
                            '[class*="SliderCaptcha"], [class*="Kaleidoscope"], ' +
                            '.vkc__SliderCaptcha-module__description, ' +
                            '.vkc__KaleidoscopeScreen-module__captchaId, ' +
                            '.vkc__SwipeButton-module__track'
                        );
                        if (slider) return 'slider';
                        var success = document.querySelector(
                            '[class*="success"], [class*="Success"], [class*="passed"], [class*="Passed"]'
                        );
                        if (success) return 'success_ui';
                        return 'none';
                    })();
                """.trimIndent()
                wv.evaluateJavascript(detectSliderJS) { rawValue ->
                    if (isFinishing || webView !== wv) return@evaluateJavascript
                    when (rawValue?.replace("\"", "") ?: "none") {
                        "slider" -> finishWithSlider()
                        "success_ui" -> postClickSliderWatcher = null
                        else -> {
                            attemptsLeft--
                            if (attemptsLeft > 0) {
                                mainHandler.postDelayed(this, 350L)
                            } else {
                                postClickSliderWatcher = null
                            }
                        }
                    }
                }
            }
        }
        postClickSliderWatcher = watcher
        mainHandler.postDelayed(watcher, 450L)
    }

    private fun simulateHumanTouch(wv: WebView, cssX: Float, cssY: Float) {
        val density = wv.resources.displayMetrics.density
        val physX = cssX * density
        val physY = cssY * density
        val downTime = SystemClock.uptimeMillis()
        val pressure = 0.5f + Random.Default.nextFloat() * 0.4f

        val downEvent = MotionEvent.obtain(
            downTime, downTime, MotionEvent.ACTION_DOWN, physX, physY, pressure, 1f, 0, 1f, 1f, 0, 0,
        )
        downEvent.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
        wv.dispatchTouchEvent(downEvent)
        downEvent.recycle()

        mainHandler.postDelayed({
            if (isFinishing || webView !== wv) return@postDelayed
            val jitterX = physX + (-1f + Random.Default.nextFloat() * 2f) * density
            val jitterY = physY + (-0.5f + Random.Default.nextFloat() * 1f) * density
            val upEvent = MotionEvent.obtain(
                downTime, SystemClock.uptimeMillis(), MotionEvent.ACTION_UP,
                jitterX, jitterY, 0f, 1f, 0, 1f, 1f, 0, 0,
            )
            upEvent.source = android.view.InputDevice.SOURCE_TOUCHSCREEN
            wv.dispatchTouchEvent(upEvent)
            upEvent.recycle()
        }, 80L + Random.Default.nextLong(0, 100))
    }

    private fun finishWithSuccess(token: String) {
        if (isFinishing) return
        CaptchaWebViewManager.completeAutoResult(Result.success(token))
        finish()
    }

    private fun finishWithSlider() {
        if (isFinishing) return
        CaptchaWebViewManager.completeAutoResult(
            Result.failure(IllegalStateException(CaptchaWebViewManager.ERROR_SLIDER_DETECTED)),
        )
        finish()
    }

    private fun finishWithError(message: String) {
        if (isFinishing) return
        if (message == CancellationReason.SUPERSEDED) {
            CaptchaWebViewManager.completeAutoResult(
                Result.failure(kotlin.coroutines.cancellation.CancellationException(message)),
            )
        } else {
            CaptchaWebViewManager.completeAutoResult(Result.failure(Exception(message)))
        }
        finish()
    }

    private fun destroyWebView(wv: WebView) {
        try {
            wv.stopLoading()
            wv.loadUrl("about:blank")
            try { wv.removeJavascriptInterface("WdttCaptcha") } catch (_: Exception) {}
            wv.webViewClient = WebViewClient()
            wv.webChromeClient = null
            wv.onPause()
            wv.destroy()
        } catch (e: Exception) {
            Log.e(TAG, "destroy: ${e.message}")
        }
    }

    private inner class CaptchaJSBridge {
        @JavascriptInterface
        fun onSuccess(token: String) {
            Log.d(TAG, "success_token (${token.length})")
            mainHandler.post { finishWithSuccess(token) }
        }

        @JavascriptInterface
        fun onSliderDetected(source: String) {
            Log.i(TAG, "slider ($source)")
            mainHandler.post { finishWithSlider() }
        }

        @JavascriptInterface
        fun onError(error: String) {
            Log.e(TAG, "VK error: $error")
            mainHandler.post { finishWithError("VK: $error") }
        }
    }

    private object CancellationReason {
        const val SUPERSEDED = "superseded"
    }

    companion object {
        private const val TAG = "AutoCaptcha"
        const val EXTRA_REDIRECT_URI = "redirectUri"

        private val VIEWPORT_WIDTHS = intArrayOf(356, 358, 360, 362, 364, 366, 368)
        private val VIEWPORT_HEIGHTS = intArrayOf(376, 378, 380, 382, 384, 386, 388)
        private val CHROME_BUILDS = arrayOf(
            "146.0.0.0", "145.0.6422.60", "145.0.6422.53",
            "144.0.6367.78", "144.0.6367.61", "143.0.6312.99",
        )

        private val INTERCEPTOR_JS = """
            (function() {
                if (window.__wdtt_interceptor_installed) return;
                window.__wdtt_interceptor_installed = true;

                const origFetch = window.fetch;
                window.fetch = async function() {
                    const args = arguments;
                    const url = args[0] || '';
                    if (typeof url === 'string' && url.includes('captchaNotRobot.check')) {
                        const response = await origFetch.apply(this, args);
                        const clone = response.clone();
                        try {
                            const data = await clone.json();
                            if (data.response && data.response.success_token) {
                                window.WdttCaptcha.onSuccess(data.response.success_token);
                            } else if (
                                data.response &&
                                data.response.show_captcha_type === 'slider'
                            ) {
                                window.WdttCaptcha.onSliderDetected('check_response');
                            } else if (data.error) {
                                window.WdttCaptcha.onError(JSON.stringify(data.error));
                            }
                        } catch(e) {}
                        return response;
                    }
                    return origFetch.apply(this, args);
                };

                const origXHROpen = XMLHttpRequest.prototype.open;
                const origXHRSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function(method, url) {
                    this._wdtt_url = url;
                    return origXHROpen.apply(this, arguments);
                };
                XMLHttpRequest.prototype.send = function() {
                    const xhr = this;
                    if (xhr._wdtt_url && xhr._wdtt_url.includes('captchaNotRobot.check')) {
                        xhr.addEventListener('load', function() {
                            try {
                                const data = JSON.parse(xhr.responseText);
                                if (data.response && data.response.success_token) {
                                    window.WdttCaptcha.onSuccess(data.response.success_token);
                                } else if (
                                    data.response &&
                                    data.response.show_captcha_type === 'slider'
                                ) {
                                    window.WdttCaptcha.onSliderDetected('check_response');
                                } else if (data.error) {
                                    window.WdttCaptcha.onError(JSON.stringify(data.error));
                                }
                            } catch(e) {}
                        });
                    }
                    return origXHRSend.apply(this, arguments);
                };
            })();
        """.trimIndent()
    }
}
