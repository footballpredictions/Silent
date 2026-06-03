package com.silent.vpn.vpn

import android.content.Context
import android.util.Log
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
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
import kotlinx.coroutines.withTimeoutOrNull
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
    private const val NETWORK_RESTART_GRACE_MS = 90_000L
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var process: Process? = null
    private var readerJob: Job? = null
    private var fallbackJob: Job? = null
    private var wgHelper: WireGuardHelper? = null
    private var apiFallbackConfig: String? = null
    private var deferredApiWgConfig: String? = null
    private var lastWgConfig: String? = null
    private var appliedConfigSource: Int = 0 // 0=none, 1=api, 2=box, 3=file
    private var appliedConfigFingerprint: String? = null
    private val wgApplyMutex = Mutex()
    private val apiOverlayMutex = Mutex()
    private var apiOverlayDepth = 0
    private var appContext: Context? = null
    private var lastParams: Params? = null
    private var lastContext: Context? = null
    private var processStartedAtMs = 0L
    private var wrapAuthTimeoutCount = 0
    private var isSwitchingTransport = false
    private val wgExcludeIps = linkedSetOf<String>()

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
        val activeHashCount: Int = HashChannelHelper.MAX_HASHES,
        val captchaMode: String = "auto",
        val apiWgConfig: String? = null,
        val isBootstrap: Boolean = false,
    )

    private var confPollJob: Job? = null
    private var readyProbeJob: Job? = null
    private var lastPolledConfFingerprint: String? = null
    private var isBootstrapMode: Boolean = false

    fun start(context: Context, params: Params, isSwitching: Boolean = false) {
        if (running.value && !isSwitching) return
        scope.launch {
            val ctx = context.applicationContext
            if (!isSwitching) {
                stopInternal(keepWg = false)
                lastError.value = null
                tunnelReady.value = false
                stats.value = ""
                activeWorkers.value = 0
                deferredApiWgConfig = null
                wrapAuthTimeoutCount = 0
                appliedConfigSource = 0
                appliedConfigFingerprint = null
                lastParams = params
                lastContext = ctx
                isBootstrapMode = params.isBootstrap
                apiFallbackConfig = params.apiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
                CaptchaWebViewManager.onTunnelStart(context)
            } else {
                apiOverlayRestoreJob?.cancel()
                apiOverlayDepth = 0
                killProcess()
                activeWorkers.value = 0
                stats.value = ""
                isSwitchingTransport = true
            }
            wgHelper = WireGuardHelper(ctx)
            appContext = ctx

            try {
                val libDir = context.applicationInfo.nativeLibraryDir
                val binaryPath = "$libDir/libclient.so"
                if (!File(binaryPath).exists()) {
                    lastError.value = "WDTT клиент не найден (libclient.so)"
                    DebugLog.e(TAG, lastError.value!!)
                    return@launch
                }
                DebugLog.i(TAG, "libclient path=$binaryPath size=${File(binaryPath).length()}")

                val workers = HashChannelHelper.workersForLibclient(
                    params.workers,
                    params.activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES),
                )
                val hashList = HashChannelHelper.hashesForLibclient(params.vkHashes, workers)
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

                if (!isSwitching) {
                    wgExcludeIps.clear()
                    // Bootstrap: app внутри VPN → исключаем server/TURN IP из AllowedIPs.
                    if (isBootstrapMode) {
                        wgExcludeIps.add(params.serverIp.trim())
                    }
                }

                DebugLog.i(
                    TAG,
                    "start peer=${params.serverIp}:${params.serverPort} n=$workers hashes=${hashList.size} switching=$isSwitching",
                )

                val cmd = listOf(
                    binaryPath,
                    "-peer", "${params.serverIp}:${params.serverPort}",
                    "-vk", hashList.joinToString(","),
                    "-n", workers.toString(),
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
                processStartedAtMs = System.currentTimeMillis()
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
        lastPolledConfFingerprint = null
        confPollJob = scope.launch {
            while (running.value) {
                if (appliedConfigSource >= 2) break
                readConfFile(context)?.let { conf ->
                    val fp = conf.hashCode().toString()
                    if (fp != lastPolledConfFingerprint) {
                        lastPolledConfFingerprint = fp
                        applyWireGuard(conf, source = 3)
                    }
                }
                delay(500)
            }
        }
    }

    /** Резерв API-WG только для bootstrap; на основном VPN ранний 0.0.0.0/0 без воркеров рвёт интернет. */
    private fun startApiFallbackTimer() {
        if (!isBootstrapMode) return
        fallbackJob?.cancel()
        val fallback = apiFallbackConfig ?: return
        fallbackJob = scope.launch {
            delay(8_000)
            if (!running.value || appliedConfigSource > 0) return@launch
            DebugLog.w(TAG, "WireGuard late API fallback (bootstrap)")
            applyWireGuard(fallback, source = 1)
        }
    }

    private fun tryApplyDeferredApiWg() {
        if (isBootstrapMode || activeWorkers.value < 1 || appliedConfigSource > 0) return
        val cfg = deferredApiWgConfig ?: apiFallbackConfig ?: return
        deferredApiWgConfig = null
        DebugLog.i(TAG, "WireGuard API apply after ${activeWorkers.value} workers")
        applyWireGuard(cfg, source = 1)
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
                            val prev = activeWorkers.value
                            activeWorkers.value = it
                            if (it > 0) wrapAuthTimeoutCount = 0
                            if (prev < 1 && it >= 1) tryApplyDeferredApiWg()
                        }
                        return@forEachLine
                    }

                    if (isBootstrapMode) {
                        Regex("""TURN UDP \(([\d.]+):\d+\)""").find(lineTrim)?.groupValues?.getOrNull(1)?.let { turnIp ->
                            if (wgExcludeIps.add(turnIp)) {
                                DebugLog.i(TAG, "Bootstrap TURN IP excluded from WG: $turnIp")
                            }
                        }
                    }

                    if (lineTrim.contains("[ДИСП] Воркер") && lineTrim.contains("зарегистрирован")) {
                        Regex("всего:\\s*(\\d+)").find(lineTrim)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            val prev = activeWorkers.value
                            activeWorkers.value = it
                            if (prev < 1 && it >= 1) tryApplyDeferredApiWg()
                        }
                        if (isSwitchingTransport && activeWorkers.value >= 1 && tunnelReady.value) {
                            isSwitchingTransport = false
                            scope.launch {
                                delay(400)
                                reloadWireGuard(context)
                            }
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

    /** Ключевые поля WG — если совпадают, повторный stop/start не нужен (box → file). */
    private fun wgConfigSemanticKey(config: String): String {
        fun field(name: String): String =
            Regex("""(?m)^$name\s*=\s*(\S+)""").find(config)?.groupValues?.getOrNull(1)?.trim().orEmpty()
        return listOf(
            field("PrivateKey"),
            field("Address"),
            field("PublicKey"),
            field("Endpoint"),
        ).joinToString("|")
    }

    private fun markTunnelReadyAfterProbe(source: Int) {
        if (tunnelReady.value) return
        readyProbeJob?.cancel()
        readyProbeJob = scope.launch {
            repeat(50) {
                delay(if (it < 25) 100L else 400L)
                if (!running.value || appliedConfigSource < source) return@launch
                if (activeWorkers.value >= 1 && wgHelper?.isTunnelUp() == true) {
                    tunnelReady.value = true
                    DebugLog.i(TAG, "tunnelReady: WG UP + ${activeWorkers.value} active workers")
                    return@launch
                }
            }
        }
    }

    /** source: 1=api, 2=box log, 3=wg-turn.conf — higher is better */
    private fun applyWireGuard(configStr: String, source: Int = 1) {
        val normalized = configStr.trim()
        if (normalized.isBlank()) return
        if (!isBootstrapMode && activeWorkers.value < 1 && source == 1) {
            deferredApiWgConfig = normalized
            DebugLog.d(TAG, "defer WG API until WDTT workers ready")
            return
        }
        val fingerprint = normalized.hashCode().toString()
        val semanticKey = wgConfigSemanticKey(normalized)
        if (source < appliedConfigSource) return

        val prevSemantic = wgConfigSemanticKey(lastWgConfig.orEmpty())
        if (appliedConfigSource > 0 && semanticKey.isNotBlank() && semanticKey == prevSemantic) {
            if (source > appliedConfigSource) {
                appliedConfigSource = source
                appliedConfigFingerprint = fingerprint
            }
            DebugLog.d(TAG, "WireGuard skip reapply (same keys, source=$source)")
            return
        }
        if (appliedConfigSource > 0 && source <= appliedConfigSource && fingerprint == appliedConfigFingerprint) return

        if (source >= 2) fallbackJob?.cancel()
        scope.launch {
            wgApplyMutex.withLock {
                if (source < appliedConfigSource) return@withLock
                val lockedPrev = wgConfigSemanticKey(lastWgConfig.orEmpty())
                if (appliedConfigSource > 0 && semanticKey.isNotBlank() && semanticKey == lockedPrev) {
                    if (source > appliedConfigSource) {
                        appliedConfigSource = source
                        appliedConfigFingerprint = fingerprint
                    }
                    DebugLog.d(TAG, "WireGuard skip reapply in lock (same keys)")
                    return@withLock
                }
                if (appliedConfigSource > 0 && source <= appliedConfigSource && fingerprint == appliedConfigFingerprint) {
                    return@withLock
                }
                lastWgConfig = normalized
                try {
                    val srcName = when (source) { 3 -> "file"; 2 -> "box"; else -> "api" }
                    wgHelper?.startTunnel(normalized, wgExcludeIps.toList(), isBootstrapMode)
                    appliedConfigSource = source
                    appliedConfigFingerprint = fingerprint
                    Log.i(TAG, "WireGuard UP ($srcName)")
                    DebugLog.i(TAG, "WireGuard UP ($srcName)")
                    markTunnelReadyAfterProbe(source)
                } catch (e: Exception) {
                    lastError.value = "WireGuard: ${e.message}"
                    Log.e(TAG, "WireGuard failed", e)
                    DebugLog.e(TAG, "WireGuard failed", e)
                    if (appliedConfigSource == 0) stop()
                }
            }
        }
    }

    fun lastWgAddress(): String? {
        val cfg = lastWgConfig ?: return null
        return Regex("""(?m)^Address\s*=\s*(\S+)""").find(cfg)?.groupValues?.getOrNull(1)
    }

    fun tunnelApiBase(): String = "http://${SilentRepository.WG_TUNNEL_GATEWAY}:8000"

    private var apiOverlayRestoreJob: Job? = null

    /** Краткий overlay только для HTTP к 10.66.66.1; основной WG — полный туннель (интернет). */
    suspend fun <T> withApiOverlay(block: suspend () -> T): T {
        if (!running.value) return block()
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return apiOverlayMutex.withLock {
            apiOverlayRestoreJob?.cancel()
            val entered = apiOverlayDepth == 0
            apiOverlayDepth++
            if (entered) {
                helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = true)
                delay(200)
            }
            try {
                block()
            } finally {
                apiOverlayDepth = (apiOverlayDepth - 1).coerceAtLeast(0)
                if (apiOverlayDepth == 0) {
                    apiOverlayRestoreJob?.cancel()
                    helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = false)
                }
            }
        }
    }

    fun isInternetReady(): Boolean =
        tunnelReady.value && activeWorkers.value >= 1 && !lastWgAddress().isNullOrBlank() && appliedConfigSource > 0

    fun restartTransport() {
        val elapsed = System.currentTimeMillis() - processStartedAtMs
        if (processStartedAtMs > 0L && elapsed < NETWORK_RESTART_GRACE_MS) {
            DebugLog.i(TAG, "[СЕТЬ] restartTransport пропущен (${elapsed}ms < ${NETWORK_RESTART_GRACE_MS}ms)")
            return
        }
        if (!tunnelReady.value || activeWorkers.value < 1) {
            DebugLog.i(TAG, "[СЕТЬ] restartTransport пропущен (туннель не готов)")
            return
        }
        val params = lastParams ?: return
        val ctx = appContext ?: return
        DebugLog.i(TAG, "[СЕТЬ] Перезапуск libclient после смены сети")
        killProcess()
        scope.launch {
            delay(1500)
            start(ctx, params, isSwitching = true)
        }
    }

    fun pause() {
        if (!running.value) return
        DebugLog.i(TAG, "pause: сеть потеряна, libclient остановлен (WG остаётся)")
        killProcess()
        activeWorkers.value = 0
        // running=true — сервис знает, что VPN-сессия ещё активна
    }

    fun resume() {
        if (running.value && process?.isAlive == true) return
        val params = lastParams ?: return
        val ctx = appContext ?: return
        DebugLog.i(TAG, "resume: сеть восстановлена, перезапуск libclient")
        running.value = true
        isSwitchingTransport = true
        scope.launch { start(ctx, params, isSwitching = true) }
    }

    fun stop() {
        scope.launch { stopInternal(keepWg = false) }
    }

    suspend fun stopAndAwait() {
        stopInternal(keepWg = false)
    }

    private fun killProcess() {
        fallbackJob?.cancel()
        confPollJob?.cancel()
        readyProbeJob?.cancel()
        readerJob?.cancel()
        val proc = process
        process = null
        if (proc != null) {
            runCatching { proc.destroy() }
            runCatching { proc.waitFor(500, java.util.concurrent.TimeUnit.MILLISECONDS) }
            if (proc.isAlive) runCatching { proc.destroyForcibly() }
        }
    }

    fun reloadWireGuard(context: Context) {
        if (!tunnelReady.value) return
        val config = lastWgConfig ?: return
        scope.launch {
            try {
                wgHelper?.stopTunnel()
                delay(200)
                wgHelper?.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode)
            } catch (e: Exception) {
                lastError.value = "WireGuard: ${e.message}"
            }
        }
    }

    private suspend fun stopInternal(keepWg: Boolean) {
        withContext(Dispatchers.IO) {
            apiOverlayRestoreJob?.cancel()
            apiOverlayDepth = 0
            deferredApiWgConfig = null
            killProcess()
            if (!keepWg) wgHelper?.stopTunnel()
            CaptchaWebViewManager.onTunnelStop()
            ManlCaptchaWebViewManager.cancelCaptcha()
            appContext = null
            lastParams = null
            lastContext = null
            appliedConfigSource = 0
            appliedConfigFingerprint = null
            running.value = false
            tunnelReady.value = false
            activeWorkers.value = 0
            stats.value = ""
            lastError.value = null
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
