package com.silent.vpn.vpn

import android.content.Context
import android.util.Log
import com.silent.vpn.util.DebugLog
import com.silent.vpn.vpn.captcha.CaptchaWebViewManager
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlin.coroutines.cancellation.CancellationException
import java.io.File

/**
 * WDTT-туннель по логике [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * libclient → box-конфиг WireGuard в логах → сразу поднять WG (без ожидания счётчика воркеров).
 */
object WdttTunnelManager {
    private const val TAG = "WdttTunnelManager"
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var process: Process? = null
    private var readerJob: Job? = null
    private var fallbackJob: Job? = null
    private var wgHelper: WireGuardHelper? = null
    private var apiFallbackConfig: String? = null
    private var lastWgConfig: String? = null
    private var appliedConfigSource: Int = 0 // 0=none, 1=api, 2=box, 3=file
    private var appliedConfigFingerprint: String? = null
    private val wgApplyMutex = Mutex()
    private var appContext: Context? = null
    private var wrapAuthTimeoutCount = 0

    val running = MutableStateFlow(false)
    val tunnelReady = MutableStateFlow(false)
    val stats = MutableStateFlow("")
    val activeWorkers = MutableStateFlow(0)
    val lastError = MutableStateFlow<String?>(null)

    data class Params(
        val serverIp: String,
        val serverPort: Int,
        val vkHashes: List<String>,
        val wdttPassword: String,
        val deviceId: String,
        val listenPort: Int = 9000,
        val workers: Int = 12,
        val captchaMode: String = "auto",
        val apiWgConfig: String? = null,
    )

    private var confPollJob: Job? = null

    fun start(context: Context, params: Params) {
        if (running.value) return
        scope.launch {
            stopInternal(keepWg = false)

            lastError.value = null
            tunnelReady.value = false
            stats.value = ""
            activeWorkers.value = 0
            wrapAuthTimeoutCount = 0
            appliedConfigSource = 0
            appliedConfigFingerprint = null
            apiFallbackConfig = params.apiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
            wgHelper = WireGuardHelper(context.applicationContext)
            appContext = context.applicationContext
            CaptchaWebViewManager.onTunnelStart(context)

            try {
                val libDir = context.applicationInfo.nativeLibraryDir
                val binaryPath = "$libDir/libclient.so"
                if (!File(binaryPath).exists()) {
                    lastError.value = "WDTT клиент не найден (libclient.so)"
                    DebugLog.e(TAG, lastError.value!!)
                    return@launch
                }
                DebugLog.i(TAG, "libclient path=$binaryPath size=${File(binaryPath).length()}")

                val hashList = params.vkHashes
                    .flatMap { it.split(Regex("[,\\s\\n]+")) }
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                    .take(3)
                if (hashList.isEmpty()) {
                    lastError.value = "Нет VK-хешей"
                    DebugLog.e(TAG, lastError.value!!)
                    return@launch
                }
                if (params.wdttPassword.isBlank()) {
                    lastError.value = "Пароль WDTT не задан"
                    DebugLog.e(TAG, lastError.value!!)
                    return@launch
                }

                DebugLog.i(TAG, "start peer=${params.serverIp}:${params.serverPort} hashes=${hashList.size} device=${params.deviceId.take(8)}")

                val cmd = listOf(
                    binaryPath,
                    "-peer", "${params.serverIp}:${params.serverPort}",
                    "-vk", hashList.joinToString(","),
                    "-n", params.workers.coerceIn(1, 128).toString(),
                    "-listen", "127.0.0.1:${params.listenPort}",
                    "-device-id", params.deviceId,
                    "-password", params.wdttPassword,
                    "-captcha-mode", sanitizeCaptchaMode(params.captchaMode),
                )

                val pb = ProcessBuilder(cmd)
                pb.directory(context.filesDir)
                pb.redirectErrorStream(true)
                pb.environment()["LD_LIBRARY_PATH"] = libDir

                deleteOldConf(context)
                process = pb.start()
                running.value = true
                DebugLog.i(TAG, "libclient started")
                delay(100)
                if (process?.isAlive != true) {
                    val code = runCatching { process?.exitValue() }.getOrNull()
                    lastError.value = "WDTT клиент упал при старте (код ${code ?: "?"}). Переустановите приложение."
                    DebugLog.e(TAG, lastError.value!!)
                    running.value = false
                    process = null
                    return@launch
                }
                startLogReader(context)
                startConfFilePoller(context)
                startApiFallbackTimer()
            } catch (e: Exception) {
                Log.e(TAG, "Start failed", e)
                DebugLog.e(TAG, "Start failed", e)
                lastError.value = e.message ?: "Ошибка запуска WDTT"
                running.value = false
            }
        }
    }

    private fun sanitizeCaptchaMode(mode: String): String = when (mode.lowercase()) {
        "rjs", "wv", "auto" -> mode.lowercase()
        else -> "auto"
    }

    private fun deleteOldConf(context: Context) {
        listOf("wg-turn.conf", "wg.conf").forEach { name ->
            runCatching { File(context.filesDir, name).delete() }
        }
    }

    private fun startConfFilePoller(context: Context) {
        confPollJob?.cancel()
        confPollJob = scope.launch {
            while (running.value) {
                if (!running.value) break
                if (tunnelReady.value && appliedConfigSource >= 3) break
                readConfFile(context)?.let { applyWireGuard(it, source = 3) }
                delay(400)
            }
        }
    }

    /** Резерв: API-конфиг, если libclient не записал wg-turn.conf. */
    private fun startApiFallbackTimer() {
        fallbackJob?.cancel()
        val fallback = apiFallbackConfig ?: return
        fallbackJob = scope.launch {
            delay(8_000)
            if (tunnelReady.value || !running.value) return@launch
            if (appliedConfigSource >= 3) return@launch
            DebugLog.w(TAG, "API fallback WireGuard (8s timeout)")
            applyWireGuard(fallback, source = 1)
        }
    }

    private fun startLogReader(context: Context) {
        readerJob?.cancel()
        readerJob = scope.launch {
            val reader = process?.inputStream?.bufferedReader() ?: return@launch
            var collectingConfig = false
            val configBuilder = StringBuilder()

            try {
                reader.forEachLine { line ->
                    val lineTrim = line
                        .replace(Regex("^\\d{4}/\\d{2}/\\d{2}\\s\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?\\s"), "")
                        .trim()
                    Log.d(TAG, lineTrim)
                    if (lineTrim.isNotBlank()) DebugLog.d(TAG, lineTrim)

                    if (lineTrim.startsWith("CAPTCHA_SOLVE|")) {
                        val payload = lineTrim.substringAfter("CAPTCHA_SOLVE|")
                        val parts = payload.split("|", limit = 3)
                        scope.launch {
                            when (parts.size) {
                                3 -> handleCaptchaSolve(parts[0], parts[1], parts[2])
                                2 -> handleCaptchaSolve("selected", parts[0], parts[1])
                                else -> writeCaptchaResult("error:invalid CAPTCHA_SOLVE format")
                            }
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("FATAL_AUTH")) {
                        val isWrapTimeout = lineTrim.contains("DTLS timeout", true) ||
                            lineTrim.contains("WRAP_AUTH_TIMEOUT", true)
                        if (isWrapTimeout && activeWorkers.value > 0) {
                            wrapAuthTimeoutCount = 0
                            DebugLog.w(TAG, "WRAP timeout on one worker, active=${activeWorkers.value}")
                            return@forEachLine
                        }
                        if (isWrapTimeout) {
                            wrapAuthTimeoutCount++
                            DebugLog.w(TAG, "WRAP handshake wait ($wrapAuthTimeoutCount)")
                            return@forEachLine
                        }
                        val reason = when {
                            lineTrim.contains("неверный пароль", true) -> "Неверный пароль WDTT"
                            lineTrim.contains("истёк", true) -> "Срок пароля истёк"
                            lineTrim.contains("другому устройству", true) -> "Пароль привязан к другому устройству"
                            else -> "Ошибка авторизации WDTT"
                        }
                        lastError.value = reason
                        DebugLog.e(TAG, reason)
                        stop()
                        return@forEachLine
                    }

                    if (lineTrim.contains("[СТАТИСТИКА]")) {
                        val msg = lineTrim.substringAfter("[СТАТИСТИКА]").trim()
                        stats.value = msg
                        Regex("Активных:\\s*(\\d+)").find(msg)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                            if (it > 0) wrapAuthTimeoutCount = 0
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[ДИСП] Воркер") && lineTrim.contains("зарегистрирован")) {
                        Regex("всего:\\s*(\\d+)").find(lineTrim)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                        }
                        apiFallbackConfig?.let { cfg ->
                            if (!tunnelReady.value) applyWireGuard(cfg, source = 1)
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[КОНФИГ]") && lineTrim.contains("Сохранён")) {
                        readConfFile(context, logFound = true)?.let { applyWireGuard(it, source = 3) }
                        return@forEachLine
                    }

                    // Как в reference: box-drawing WireGuard → сразу UP
                    if (line.contains("╔") && line.contains("WireGuard")) {
                        collectingConfig = true
                        configBuilder.clear()
                        return@forEachLine
                    }
                    if (collectingConfig) {
                        if (line.contains("╚")) {
                            collectingConfig = false
                            val configStr = configBuilder.toString().trim()
                            if (configStr.isNotBlank()) {
                                applyWireGuard(configStr, source = 2)
                            }
                        } else if (line.contains("║")) {
                            val content = line.replace("║", "").trim()
                            if (content.isNotEmpty()) configBuilder.appendLine(content)
                        }
                        return@forEachLine
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Reader error", e)
                DebugLog.e(TAG, "Reader error", e)
            } finally {
                val proc = process
                val exitCode = runCatching { proc?.exitValue() }.getOrNull()
                if (exitCode != null) {
                    DebugLog.w(TAG, "libclient exited code=$exitCode ready=${tunnelReady.value}")
                }
                if (!tunnelReady.value) {
                    running.value = false
                }
                process = null
            }
        }
    }

    private fun readConfFile(context: Context, logFound: Boolean = false): String? {
        for (name in listOf("wg-turn.conf", "wg.conf")) {
            val f = File(context.filesDir, name)
            if (f.exists() && f.length() > 20) {
                val text = runCatching { f.readText().trim() }.getOrNull()
                if (!text.isNullOrBlank() && text.contains("[Interface]")) {
                    if (logFound) {
                        Log.i(TAG, "WG config from $name")
                        DebugLog.i(TAG, "WG config from $name")
                    }
                    return text
                }
            }
        }
        return null
    }

    /** source: 1=api, 2=box log, 3=wg-turn.conf — higher is better */
    private fun applyWireGuard(configStr: String, source: Int = 1) {
        val normalized = configStr.trim()
        if (normalized.isBlank()) return
        val fingerprint = normalized.hashCode().toString()
        if (source < appliedConfigSource) return
        if (tunnelReady.value && source <= appliedConfigSource && fingerprint == appliedConfigFingerprint) return

        fallbackJob?.cancel()
        scope.launch {
            wgApplyMutex.withLock {
                if (source < appliedConfigSource) return@withLock
                if (tunnelReady.value && source <= appliedConfigSource && fingerprint == appliedConfigFingerprint) {
                    return@withLock
                }
                val upgrade = tunnelReady.value && source > appliedConfigSource
                lastWgConfig = normalized
                try {
                    if (upgrade) {
                        DebugLog.i(TAG, "WireGuard upgrade config source=$source")
                        wgHelper?.stopTunnel()
                        delay(150)
                    }
                    val srcName = when (source) { 3 -> "file"; 2 -> "box"; else -> "api" }
                    wgHelper?.startTunnel(normalized)
                    appliedConfigSource = source
                    appliedConfigFingerprint = fingerprint
                    if (!tunnelReady.value) {
                        tunnelReady.value = true
                    }
                    Log.i(TAG, "WireGuard UP ($srcName)")
                    DebugLog.i(TAG, "WireGuard UP ($srcName)")
                } catch (e: Exception) {
                    lastError.value = "WireGuard: ${e.message}"
                    Log.e(TAG, "WireGuard failed", e)
                    DebugLog.e(TAG, "WireGuard failed", e)
                    if (appliedConfigSource == 0) stop()
                }
            }
        }
    }

    fun stop() {
        scope.launch { stopInternal(keepWg = false) }
    }

    fun reloadWireGuard(context: Context) {
        if (!tunnelReady.value) return
        val config = lastWgConfig ?: return
        scope.launch {
            try {
                wgHelper?.stopTunnel()
                delay(200)
                wgHelper?.startTunnel(config)
            } catch (e: Exception) {
                lastError.value = "WireGuard: ${e.message}"
            }
        }
    }

    private suspend fun stopInternal(keepWg: Boolean) {
        withContext(Dispatchers.IO) {
            fallbackJob?.cancel()
            confPollJob?.cancel()
            readerJob?.cancel()
            val proc = process
            process = null
            if (proc != null) {
                runCatching { proc.destroy() }
                runCatching { proc.waitFor(500, java.util.concurrent.TimeUnit.MILLISECONDS) }
                if (proc.isAlive) runCatching { proc.destroyForcibly() }
            }
            if (!keepWg) wgHelper?.stopTunnel()
            CaptchaWebViewManager.onTunnelStop()
            ManlCaptchaWebViewManager.cancelCaptcha()
            appContext = null
            appliedConfigSource = 0
            appliedConfigFingerprint = null
            running.value = false
            tunnelReady.value = false
            activeWorkers.value = 0
            stats.value = ""
        }
    }

    private suspend fun handleCaptchaSolve(requestMode: String, redirectUri: String, sessionToken: String) {
        val ctx = appContext ?: run {
            writeCaptchaResult("error:context is null")
            return
        }
        DebugLog.i(TAG, "CAPTCHA solve mode=$requestMode")
        try {
            val token = when (requestMode.lowercase()) {
                "auto" -> CaptchaWebViewManager.solveCaptchaAsync(redirectUri, sessionToken)
                "manual" -> ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                else -> solveAutoWebViewCaptcha(ctx, redirectUri, sessionToken)
            }
            DebugLog.i(TAG, "CAPTCHA solved (${token.length} chars)")
            writeCaptchaResult(token)
        } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
            DebugLog.e(TAG, "CAPTCHA timeout")
            writeCaptchaResult("error:timeout")
        } catch (e: CancellationException) {
            writeCaptchaResult("error:cancelled")
        } catch (e: Exception) {
            DebugLog.e(TAG, "CAPTCHA failed: ${e.message}")
            writeCaptchaResult("error:${e.message ?: "unknown"}")
        }
    }

    private suspend fun solveAutoWebViewCaptcha(
        ctx: Context,
        redirectUri: String,
        sessionToken: String,
    ): String {
        repeat(2) { attempt ->
            try {
                return CaptchaWebViewManager.solveCaptchaAsync(redirectUri, sessionToken)
            } catch (e: IllegalStateException) {
                if (e.message == CaptchaWebViewManager.ERROR_SLIDER_DETECTED) {
                    DebugLog.w(TAG, "CAPTCHA slider -> manual WebView")
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
                throw e
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                if (attempt == 1) {
                    DebugLog.w(TAG, "CAPTCHA auto WBV timeout -> manual")
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
            }
        }
        return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
    }

    private fun writeCaptchaResult(result: String) {
        val proc = process ?: return
        if (!proc.isAlive) return
        runCatching {
            val line = "CAPTCHA_RESULT|$result\n"
            proc.outputStream.write(line.toByteArray(Charsets.UTF_8))
            proc.outputStream.flush()
            DebugLog.d(TAG, "CAPTCHA_RESULT sent (${result.take(24)}…)")
        }.onFailure {
            DebugLog.e(TAG, "CAPTCHA write failed: ${it.message}")
        }
    }
}
