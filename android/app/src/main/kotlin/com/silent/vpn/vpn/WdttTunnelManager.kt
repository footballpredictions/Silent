package com.silent.vpn.vpn

import android.content.Context
import android.util.Log
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
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
        apiFallbackConfig = params.apiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
        wgHelper = WireGuardHelper(context.applicationContext)

            try {
                val binaryPath = context.applicationInfo.nativeLibraryDir + "/libclient.so"
                if (!File(binaryPath).exists()) {
                    lastError.value = "WDTT клиент не найден (libclient.so)"
                    DebugLog.e(TAG, lastError.value!!)
                    return@launch
                }

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
                pb.environment()["LD_LIBRARY_PATH"] = context.applicationInfo.nativeLibraryDir

                deleteOldConf(context)
                process = pb.start()
                running.value = true
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
            while (running.value && !tunnelReady.value) {
                delay(2000)
                if (!running.value || tunnelReady.value) break
                readConfFile(context)?.let { applyWireGuard(it) }
            }
        }
    }

    /** API fallback: libclient может не вывести box-конфиг — поднимаем WG из ответа сервера. */
    private fun startApiFallbackTimer() {
        fallbackJob?.cancel()
        val fallback = apiFallbackConfig ?: return
        fallbackJob = scope.launch {
            for (waitMs in listOf(3000L, 5000L, 7000L, 5000L)) {
                delay(waitMs)
                if (tunnelReady.value || !running.value) return@launch
                Log.w(TAG, "API fallback WireGuard config")
                DebugLog.w(TAG, "API fallback WireGuard config")
                applyWireGuard(fallback)
            }
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

                    if (lineTrim.contains("FATAL_AUTH") &&
                        !lineTrim.contains("DTLS timeout", true) &&
                        !lineTrim.contains("WRAP_AUTH_TIMEOUT", true)
                    ) {
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
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[ДИСП] Воркер") && lineTrim.contains("зарегистрирован")) {
                        Regex("всего:\\s*(\\d+)").find(lineTrim)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                        }
                        apiFallbackConfig?.let { cfg ->
                            if (!tunnelReady.value) applyWireGuard(cfg)
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[КОНФИГ]") && lineTrim.contains("Сохранён")) {
                        readConfFile(context)?.let { applyWireGuard(it) }
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
                                applyWireGuard(configStr)
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
                if (!tunnelReady.value) {
                    running.value = false
                }
                process = null
            }
        }
    }

    private fun readConfFile(context: Context): String? {
        for (name in listOf("wg-turn.conf", "wg.conf")) {
            val f = File(context.filesDir, name)
            if (f.exists() && f.length() > 20) {
                val text = runCatching { f.readText().trim() }.getOrNull()
                if (!text.isNullOrBlank() && text.contains("[Interface]")) {
                    Log.i(TAG, "WG config from $name")
                    DebugLog.i(TAG, "WG config from $name")
                    return text
                }
            }
        }
        return null
    }

    private fun applyWireGuard(configStr: String) {
        if (tunnelReady.value) return
        fallbackJob?.cancel()
        lastWgConfig = configStr
        scope.launch {
            try {
                wgHelper?.startTunnel(configStr)
                tunnelReady.value = true
                Log.i(TAG, "WireGuard UP")
                DebugLog.i(TAG, "WireGuard UP")
            } catch (e: Exception) {
                lastError.value = "WireGuard: ${e.message}"
                Log.e(TAG, "WireGuard failed", e)
                DebugLog.e(TAG, "WireGuard failed", e)
                stop()
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
            running.value = false
            tunnelReady.value = false
            activeWorkers.value = 0
            stats.value = ""
        }
    }
}
