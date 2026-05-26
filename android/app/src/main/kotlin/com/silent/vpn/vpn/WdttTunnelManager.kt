package com.silent.vpn.vpn

import android.content.Context
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

object WdttTunnelManager {
    private const val TAG = "WdttTunnelManager"
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var process: Process? = null
    private var readerJob: Job? = null
    private var wgHelper: WireGuardHelper? = null
    private var serverIp: String = ""
    private val excludeIPs = linkedSetOf<String>()
    private var pendingConfig: String? = null
    private var confReady = false
    private var wgApplied = false

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
        val workers: Int = 16,
    )

    fun start(context: Context, params: Params) {
        if (running.value) return
        lastError.value = null
        tunnelReady.value = false
        wgApplied = false
        confReady = false
        pendingConfig = null
        excludeIPs.clear()
        serverIp = params.serverIp
        if (params.serverIp.isNotBlank()) excludeIPs.add(params.serverIp)
        activeWorkers.value = 0
        wgHelper = WireGuardHelper(context.applicationContext)

        scope.launch {
            try {
                val binaryPath = context.applicationInfo.nativeLibraryDir + "/libclient.so"
                if (!File(binaryPath).exists()) {
                    lastError.value = "WDTT клиент не найден (libclient.so)"
                    return@launch
                }

                val hashes = params.vkHashes.filter { it.isNotBlank() }.take(3).joinToString(",")
                if (hashes.isEmpty()) {
                    lastError.value = "Нет VK-хешей"
                    return@launch
                }

                val peer = "${params.serverIp}:${params.serverPort}"
                val cmd = listOf(
                    binaryPath,
                    "-peer", peer,
                    "-vk", hashes,
                    "-n", params.workers.toString(),
                    "-listen", "127.0.0.1:${params.listenPort}",
                    "-device-id", params.deviceId,
                    "-password", params.wdttPassword,
                    "-captcha-mode", "rjs",
                )

                val pb = ProcessBuilder(cmd)
                pb.directory(context.filesDir)
                pb.redirectErrorStream(true)
                pb.environment()["LD_LIBRARY_PATH"] = context.applicationInfo.nativeLibraryDir

                process = pb.start()
                running.value = true
                startLogReader(context)
            } catch (e: Exception) {
                Log.e(TAG, "Start failed", e)
                lastError.value = e.message ?: "Ошибка запуска WDTT"
                running.value = false
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
                    val lineTrim = line.replace(Regex("^\\d{4}/\\d{2}/\\d{2}\\s\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?\\s"), "").trim()
                    Log.d(TAG, lineTrim)

                    Regex("TURN UDP \\(([\\d.]+):\\d+\\)").find(lineTrim)?.groupValues?.getOrNull(1)?.let {
                        excludeIPs.add(it)
                    }

                    if (lineTrim.contains("FATAL_AUTH")) {
                        lastError.value = "Ошибка авторизации WDTT"
                        stop()
                        return@forEachLine
                    }

                    if (lineTrim.contains("[СТАТИСТИКА]")) {
                        val msg = lineTrim.substringAfter("[СТАТИСТИКА]").trim()
                        stats.value = msg
                        Regex("Активных:\\s*(\\d+)").find(msg)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                            tryApplyWireGuard(context)
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[ДИСП] Воркер") && lineTrim.contains("зарегистрирован")) {
                        Regex("всего:\\s*(\\d+)").find(lineTrim)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                            tryApplyWireGuard(context)
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[КОНФИГ]") && lineTrim.contains("Сохранён")) {
                        return@forEachLine
                    }

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
                                pendingConfig = configStr
                                confReady = true
                                tryApplyWireGuard(context)
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
            } finally {
                running.value = false
                tunnelReady.value = false
                process = null
            }
        }
    }

    private fun tryApplyWireGuard(context: Context) {
        if (wgApplied || !confReady || activeWorkers.value < 2) return
        val config = pendingConfig ?: return
        wgApplied = true
        scope.launch {
            delay(500)
            try {
                wgHelper?.startTunnel(config, excludeIPs.toList())
                tunnelReady.value = true
                Log.i(TAG, "WireGuard up, workers=${activeWorkers.value}, exclude=${excludeIPs.size}")
            } catch (e: Exception) {
                wgApplied = false
                lastError.value = "WireGuard: ${e.message}"
                stop()
            }
        }
    }

    fun stop() {
        scope.launch {
            withContext(Dispatchers.IO) {
                readerJob?.cancel()
                process?.destroy()
                process = null
                wgHelper?.stopTunnel()
                running.value = false
                tunnelReady.value = false
                activeWorkers.value = 0
                stats.value = ""
                wgApplied = false
                confReady = false
                pendingConfig = null
                excludeIPs.clear()
            }
        }
    }
}
