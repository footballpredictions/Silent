package com.silent.vpn.vpn.captcha

import android.content.Context
import android.content.Intent
import android.util.Log
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.util.concurrent.atomic.AtomicReference
import kotlin.coroutines.cancellation.CancellationException

/**
 * Оркестратор авто-капчи: запускает невидимую [AutoCaptchaActivity] и ждёт success_token.
 */
object CaptchaWebViewManager {

    private const val TAG = "CaptchaWV"
    private const val CAPTCHA_TIMEOUT_MS = 29_000L
    const val ERROR_SLIDER_DETECTED = "slider_detected"

    @Volatile
    private var isTunnelActive = false

    @Volatile
    private var appContext: Context? = null

    @Volatile
    var activeAutoActivity: AutoCaptchaActivity? = null

    private val captchaMutex = Mutex()
    private val pendingResult = AtomicReference<CompletableDeferred<Result<String>>?>(null)

    fun onTunnelStart(context: Context) {
        appContext = context.applicationContext
        isTunnelActive = true
        Log.d(TAG, "Туннель активен")
    }

    fun onTunnelStop() {
        isTunnelActive = false
        cancelCurrentSolve()
        appContext = null
        Log.d(TAG, "Туннель остановлен")
    }

    fun cancelCurrentSolve() {
        activeAutoActivity?.cancelSolve()
        activeAutoActivity = null
        cancelPendingResult("superseded")
    }

    suspend fun solveCaptchaAsync(redirectUri: String, sessionToken: String, onStep: (String) -> Unit = {}): String {
        if (!isTunnelActive) throw IllegalStateException("WV не готов — туннель не активен")
        val ctx = appContext ?: throw IllegalStateException("WV не готов — контекст null")

        return captchaMutex.withLock {
            val deferred = CompletableDeferred<Result<String>>()
            pendingResult.set(deferred)
            try {
                withContext(Dispatchers.Main) {
                    val intent = Intent(ctx, AutoCaptchaActivity::class.java).apply {
                        putExtra(AutoCaptchaActivity.EXTRA_REDIRECT_URI, redirectUri)
                        addFlags(
                            Intent.FLAG_ACTIVITY_NEW_TASK or
                                Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS or
                                Intent.FLAG_ACTIVITY_NO_ANIMATION or
                                Intent.FLAG_ACTIVITY_SINGLE_TOP,
                        )
                    }
                    ctx.startActivity(intent)
                }
                withTimeout(CAPTCHA_TIMEOUT_MS) {
                    deferred.await().getOrThrow()
                }
            } catch (e: CancellationException) {
                throw e
            } finally {
                abortAutoIfPending("solve ended")
                activeAutoActivity?.finish()
                activeAutoActivity = null
            }
        }
    }

    internal fun completeAutoResult(result: Result<String>) {
        val deferred = pendingResult.getAndSet(null) ?: return
        if (!deferred.isCompleted) {
            deferred.complete(result)
        }
    }

    internal fun abortAutoIfPending(reason: String) {
        val deferred = pendingResult.get() ?: return
        if (!deferred.isCompleted) {
            completeAutoResult(Result.failure(Exception(reason)))
        }
    }

    private fun cancelPendingResult(reason: String) {
        val deferred = pendingResult.getAndSet(null) ?: return
        if (!deferred.isCompleted) {
            deferred.complete(Result.failure(CancellationException(reason)))
        }
    }
}
