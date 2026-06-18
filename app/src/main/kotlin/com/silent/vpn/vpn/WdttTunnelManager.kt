package com.silent.vpn.vpn

import android.content.Context
import androidx.compose.runtime.Stable
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
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.CancellationException
import java.io.File
import java.util.concurrent.atomic.AtomicInteger

/**
 * WDTT-туннель — логика как в [proxy-turn-vk-android](https://github.com/amurcanov/proxy-turn-vk-android):
 * libclient → box WireGuard → сразу UP; воркеры набираются в том же процессе.
 */
@Stable
data class LogEntry(
    val key: String,
    val message: String,
    val count: Int = 1,
    val priority: Int = 99,
    val isError: Boolean = false,
)

object WdttTunnelManager {
    private const val TAG = "WdttTunnelManager"
    private const val NETWORK_RESTART_GRACE_MS = 30_000L

    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    @Volatile var isLoggingEnabled = true

    private var process: Process? = null
    private var readerJob: Job? = null
    private var watchdogJob: Job? = null
    private var bootstrapFallbackJob: Job? = null
    private var mainWgFallbackJob: Job? = null
    private var confPollJob: Job? = null
    private var wgConfigRetryJob: Job? = null
    private var wgHelper: WireGuardHelper? = null
    private var deferredApiWgConfig: String? = null
    private var wgApplyJob: Job? = null
    @Volatile private var wgApplyScheduled = false
    private var lastWgApplyAttemptMs = 0L
    private var pendingWgConfigOverride: String? = null
    @Volatile private var wgConfigPending = false
    private val startStopMutex = Mutex()
    private val wgApplyMutex = Mutex()

    private var floodCount = 0
    private var mismatchCount = 0
    private var refusedCount = 0
    private var currentHashErrorCount = 0
    private var wrapAuthTimeoutCount = 0
    var processStartedAtMs = 0L
    private var lastActiveAtMs = 0L

    private var lastParams: Params? = null
    private var lastContext: Context? = null
    private var lastWgConfig: String? = null
    private var isBootstrapMode = false
    private val wgExcludeIps = linkedSetOf<String>()
    private var sessionVkHashes: List<String> = emptyList()
    private val groupHashPrefix = mutableMapOf<Int, String>()

    @Volatile private var apiOverlayActive = false
    @Volatile private var suppressNetworkRecovery = false
    private var overlayRestoreSuppressed = false
    private var lastOverlayEndedMs = 0L
    private val minOverlayIntervalMs = 60_000L
    private val overlayEnterDelayMs = 800L

    private var captchaSolveJob: Job? = null
    private val captchaSession = AtomicInteger(0)
    @Volatile private var captchaInProgress = false
    @Volatile private var captchaManualInProgress = false
    private var lastCaptchaRedirectUri: String? = null
    private var lastCaptchaScheduledMs = 0L

    val running = MutableStateFlow(false)
    val tunnelReady = MutableStateFlow(false)
    val logs = MutableStateFlow<List<LogEntry>>(emptyList())
    val unreadErrorCount = MutableStateFlow(0)
    val stats = MutableStateFlow("Ожидание данных…")
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

    class ApiOverlayBlockedException(message: String) : Exception(message)

    fun clearUnreadErrors() {
        unreadErrorCount.value = 0
    }

    fun clearLogs() {
        logs.value = emptyList()
        if (!running.value) activeWorkers.value = 0
    }

    private fun updateLog(key: String, message: String, priority: Int, isError: Boolean = false) {
        if (!isLoggingEnabled) return
        if (isError && logs.value.none { it.key == key }) {
            unreadErrorCount.value++
        }
        logs.update { currentList ->
            val current = currentList.toMutableList()
            val index = current.indexOfFirst { it.key == key }
            if (index != -1) {
                val entry = current[index]
                current[index] = entry.copy(
                    count = entry.count + 1,
                    message = message,
                    priority = priority,
                    isError = isError,
                )
            } else {
                current.add(LogEntry(key, message, 1, priority, isError))
            }
            val sorted = current.sortedWith(
                compareBy({ it.priority }, { if (it.isError) 1 else 0 }, { it.key }),
            )
            if (sorted.size > 100) sorted.takeLast(100) else sorted
        }
    }

    fun start(context: Context, params: Params, isSwitching: Boolean = false) {
        scope.launch {
            startStopMutex.withLock {
                try {
                    if (running.value && !isSwitching) return@withLock

                    val appContext = context.applicationContext
                    if (!isSwitching) {
                        overlayRestoreSuppressed = false
                        clearLogs()
                        tunnelReady.value = false
                        stats.value = "Ожидание данных…"
                        activeWorkers.value = 0
                        lastError.value = null
                        floodCount = 0
                        mismatchCount = 0
                        refusedCount = 0
                        currentHashErrorCount = 0
                        wrapAuthTimeoutCount = 0
                        processStartedAtMs = 0L
                        lastActiveAtMs = 0L
                        lastParams = params
                        lastContext = appContext
                        isBootstrapMode = params.isBootstrap
                        // GETCONF — основной путь; apiWgConfig — отложенный fallback (10 с).
                        deferredApiWgConfig = params.apiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
                        sessionVkHashes = emptyList()
                        groupHashPrefix.clear()
                        wgExcludeIps.clear()
                        wgConfigPending = false
                        CaptchaWebViewManager.onTunnelStart(context)
                    } else {
                        killProcess()
                        activeWorkers.value = 0
                        stats.value = "Ожидание данных…"
                    }

                    wgHelper = WireGuardHelper(appContext)

                    val workers = if (params.isBootstrap) {
                        params.workers.coerceIn(HashChannelHelper.WORKERS_PER_GROUP, 9)
                    } else {
                        HashChannelHelper.workersForLibclient(
                            params.workers,
                            params.activeHashCount.coerceIn(1, HashChannelHelper.MAX_HASHES),
                        )
                    }
                    val hashList = HashChannelHelper.hashesForLibclient(params.vkHashes, workers)
                    if (hashList.isEmpty()) {
                        updateLog("hash_error", "Ошибка: хеш не указан", 99, true)
                        lastError.value = "Нет VK-хешей"
                        running.value = false
                        return@withLock
                    }
                    if (params.wdttPassword.isBlank()) {
                        updateLog("password_error", "Ошибка: пароль WDTT не указан", 99, true)
                        lastError.value = "Пароль WDTT не задан"
                        running.value = false
                        return@withLock
                    }

                    sessionVkHashes = hashList
                    updateLog(
                        "config_info",
                        "[${if (isBootstrapMode) "Bootstrap" else "Основной"}] Хешей=${hashList.size}, Потоков=$workers",
                        1,
                    )
                    updateLog(
                        "device_id",
                        "libclient device-id: ${params.deviceId.take(4)}… (${params.deviceId.length} симв.)",
                        1,
                    )

                    val libDir = appContext.applicationInfo.nativeLibraryDir
                    val binaryPath = "$libDir/libclient.so"
                    if (!File(binaryPath).exists()) {
                        updateLog("binary_error", "Ошибка: libclient.so не найден", 99, true)
                        lastError.value = "WDTT клиент не найден"
                        running.value = false
                        return@withLock
                    }

                    deleteOldConf(appContext)

                    val cmd = buildList {
                        add(binaryPath)
                        addAll(
                            listOf(
                                "-peer", "${params.serverIp}:${params.serverPort}",
                                "-vk", hashList.joinToString(","),
                                "-n", workers.toString(),
                                "-listen", "127.0.0.1:${params.listenPort}",
                                "-device-id", params.deviceId,
                                "-password", params.wdttPassword,
                                "-captcha-mode", sanitizeCaptchaMode(params.captchaMode),
                            ),
                        )
                        systemDnsForLibclient(appContext).let { dns ->
                            add("-sys-dns")
                            add(dns)
                        }
                        add("-fingerprint")
                        add("chrome")
                        add("-client-ids")
                        add("6287487,8202606")
                    }

                    val pb = ProcessBuilder(cmd)
                    pb.directory(appContext.filesDir)
                    pb.redirectErrorStream(true)
                    pb.environment()["LD_LIBRARY_PATH"] = libDir

                    process = pb.start()
                    processStartedAtMs = System.currentTimeMillis()
                    wrapAuthTimeoutCount = 0
                    lastActiveAtMs = 0L
                    running.value = true
                    updateLog("libclient_start", "libclient запущен (n=$workers)", 1)
                    startLogReader()
                    startConfFilePoller(appContext)
                    startWatchdog(appContext, params)
                    scheduleBootstrapApiFallback(params)
                    scheduleMainApiWgFallback(params)
                    scheduleWgConfigRetry()
                } catch (e: Exception) {
                    updateLog("critical_start_error", "Критическая ошибка: ${e.message}", 99, true)
                    lastError.value = e.message ?: "Ошибка запуска WDTT"
                    running.value = false
                }
            }
        }
    }

    private fun sanitizeCaptchaMode(mode: String): String = when (mode.lowercase()) {
        "rjs", "wv", "auto" -> mode.lowercase()
        else -> "auto"
    }

    private fun systemDnsForLibclient(context: Context): String {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? android.net.ConnectivityManager
            ?: return DEFAULT_LIBCLIENT_DNS
        val linkDns = cm.getLinkProperties(cm.activeNetwork)?.dnsServers
            ?.mapNotNull { addr ->
                addr.hostAddress?.takeIf { it.isNotBlank() }?.let { host ->
                    if (host.contains(':')) host else "$host:53"
                }
            }
            ?.distinct()
            ?.joinToString(",")
            ?.takeIf { it.isNotBlank() }
        return linkDns ?: DEFAULT_LIBCLIENT_DNS
    }

    private const val DEFAULT_LIBCLIENT_DNS = "1.1.1.1:53,77.88.8.8:53"

    private fun deleteOldConf(context: Context) {
        listOf("wg-turn.conf", "wg.conf").forEach { name ->
            runCatching { File(context.filesDir, name).delete() }
        }
    }

    /** Опрос wg-turn.conf — libclient часто пишет только в файл, без box в stdout. */
    private fun startConfFilePoller(context: Context) {
        confPollJob?.cancel()
        confPollJob = scope.launch {
            while (isActive && running.value && !tunnelReady.value) {
                readConfFile(context)?.let { conf ->
                    wgConfigPending = true
                    updateLog("wg_file", "WireGuard конфиг из файла", 2)
                    scheduleWireGuardApply(conf)
                    return@launch
                }
                delay(400)
            }
        }
    }

    /** Bootstrap: API-конфиг (bootstrap-config), если GETCONF ещё не вернул файл. */
    private fun scheduleBootstrapApiFallback(params: Params) {
        bootstrapFallbackJob?.cancel()
        val fallback = deferredApiWgConfig ?: return
        if (!params.isBootstrap) return
        bootstrapFallbackJob = scope.launch {
            delay(2_000)
            if (!running.value || tunnelReady.value) return@launch
            updateLog("wg_api_fallback", "WireGuard из bootstrap-config API", 2)
            scheduleWireGuardApply(fallback)
        }
    }

    /** Main VPN: WG из кеша только если GETCONF не пришёл за 10 с (не раньше — иначе 0 трафика). */
    private fun scheduleMainApiWgFallback(params: Params) {
        mainWgFallbackJob?.cancel()
        val fallback = deferredApiWgConfig ?: return
        if (params.isBootstrap) return
        mainWgFallbackJob = scope.launch {
            delay(10_000)
            if (!running.value || tunnelReady.value) return@launch
            if (readConfFile(lastContext) != null) return@launch
            updateLog("wg_cache_fallback", "WireGuard из кеша (GETCONF timeout)", 2)
            scheduleWireGuardApply(fallback)
        }
    }

    /** Как reference: WG когда libclient выдал GETCONF (файл/stdout). */
    private fun tryApplyWireGuardUp() {
        if (tunnelReady.value) return
        readConfFile(lastContext)?.let {
            scheduleWireGuardApply(it)
            return
        }
        if (isBootstrapMode) {
            scheduleWireGuardApply()
        }
    }

    private fun scheduleWireGuardApply(configOverride: String? = null) {
        if (tunnelReady.value) return
        configOverride?.trim()?.takeIf { it.contains("[Interface]") }?.let {
            pendingWgConfigOverride = it
        }
        val now = System.currentTimeMillis()
        if (now - lastWgApplyAttemptMs < 400L && wgApplyScheduled) return
        lastWgApplyAttemptMs = now
        if (wgApplyScheduled) return
        wgApplyScheduled = true
        scope.launch {
            delay(350)
            wgApplyScheduled = false
            if (tunnelReady.value || !running.value) return@launch
            val conf = pendingWgConfigOverride
                ?: readConfFile(lastContext)
                ?: if (isBootstrapMode) {
                    deferredApiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
                } else {
                    null
                }
            pendingWgConfigOverride = null
            if (conf.isNullOrBlank()) {
                if (!wgConfigPending) {
                    updateLog("wg_wait", "Ожидание WireGuard-конфига от сервера (GETCONF)…", 50)
                }
                return@launch
            }
            applyWireGuard(conf)
        }
    }

    /** Пока WG не поднят — опрашиваем файл/API после появления воркеров. */
    private fun scheduleWgConfigRetry() {
        wgConfigRetryJob?.cancel()
        wgConfigRetryJob = scope.launch {
            repeat(90) {
                if (tunnelReady.value || !running.value) return@launch
                if (activeWorkers.value >= 1) {
                    if (!tunnelReady.value) {
                        scheduleWireGuardApply()
                    }
                }
                if (tunnelReady.value) return@launch
                delay(500)
            }
        }
    }

    private fun startLogReader() {
        readerJob?.cancel()
        readerJob = scope.launch {
            val reader = process?.inputStream?.bufferedReader() ?: return@launch
            var collectingConfig = false
            val configBuilder = StringBuilder()
            try {
                var lastResetTime = System.currentTimeMillis()
                reader.forEachLine { line ->
                    val now = System.currentTimeMillis()
                    if (now - lastResetTime > 60_000) {
                        refusedCount = 0
                        floodCount = 0
                        mismatchCount = 0
                        currentHashErrorCount = 0
                        lastResetTime = now
                    }

                    val lineTrim = line
                        .replace(Regex("^\\d{4}/\\d{2}/\\d{2}\\s\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?\\s"), "")
                        .trim()

                    if (lineTrim.startsWith("CAPTCHA_SOLVE|")) {
                        val payload = lineTrim.substringAfter("CAPTCHA_SOLVE|")
                        scheduleCaptchaSolve(payload.split("|", limit = 3))
                        return@forEachLine
                    }

                    if (lineTrim.contains("FATAL_AUTH")) {
                        val isWrapTimeout = lineTrim.contains("DTLS timeout", true) ||
                            lineTrim.contains("WRAP_AUTH_TIMEOUT", true)
                        if (isWrapTimeout) {
                            if (activeWorkers.value > 0) {
                                wrapAuthTimeoutCount = 0
                                updateLog(
                                    "wrap_timeout_recovered",
                                    "[WRAP] Handshake на одном потоке, активных=${activeWorkers.value}",
                                    50,
                                    true,
                                )
                            } else {
                                wrapAuthTimeoutCount++
                                updateLog(
                                    "wrap_timeout_wait",
                                    "[WRAP] Handshake не подтвердился ($wrapAuthTimeoutCount)",
                                    50,
                                    true,
                                )
                            }
                            return@forEachLine
                        }
                        val reason = when {
                            lineTrim.contains("неверный пароль", true) -> "Неверный пароль WDTT"
                            lineTrim.contains("истёк", true) -> "Срок пароля истёк"
                            lineTrim.contains("другому устройству", true) -> "Пароль привязан к другому устройству"
                            else -> "Ошибка авторизации WDTT"
                        }
                        lastError.value = reason
                        handleCriticalError("🔒 $reason")
                        return@forEachLine
                    }

                    if (lineTrim.contains("[СТАТИСТИКА]")) {
                        val msg = lineTrim.substringAfter("[СТАТИСТИКА]").trim()
                        stats.value = msg
                        val prevActive = activeWorkers.value
                        Regex("Активных:\\s*(\\d+)").find(msg)?.groupValues?.getOrNull(1)?.toIntOrNull()?.let {
                            activeWorkers.value = it
                            if (it > 0) {
                                lastActiveAtMs = now
                                wrapAuthTimeoutCount = 0
                                if (prevActive < 1) tryApplyWireGuardUp()
                            }
                        }
                        updateLog("stats", "[СТАТИСТИКА] $msg", 3)
                        return@forEachLine
                    }

                    Regex("""TURN UDP \(([\d.]+):\d+\)""").find(lineTrim)?.groupValues?.getOrNull(1)?.let { turnIp ->
                        if (isBootstrapMode && wgExcludeIps.add(turnIp)) {
                            reloadBootstrapAllowedIps()
                        }
                    }

                    if (lineTrim.contains("Конфиг получен") ||
                        lineTrim.contains("Ошибка конфига") ||
                        lineTrim.contains("Сервер ещё не выдал") ||
                        lineTrim.contains("[КОНФИГ]")
                    ) {
                        val isErr = lineTrim.contains("Ошибка", true)
                        val isNoconf = lineTrim.contains("Сервер ещё не выдал")
                        val msg = if (isNoconf) {
                            "$lineTrim (GETCONF через TURN — HTTPS не нужен; если повторяется: пул IP на VPS или нужен boot: device-id)"
                        } else {
                            lineTrim
                        }
                        updateLog("getconf_${lineTrim.take(20).hashCode()}", msg, 2, isErr || isNoconf)
                        if (lineTrim.contains("Конфиг получен") || lineTrim.contains("Сохранён")) {
                            wgConfigPending = true
                        }
                        if (lineTrim.contains("Конфиг получен")) {
                            scope.launch {
                                delay(300)
                                readConfFile(lastContext)?.let { scheduleWireGuardApply(it) }
                            }
                        }
                    }

                    if (!isBootstrapMode) {
                        Regex("""\[ГРУППА #(\d+)\] Запрос кредов \(хеш: (\S+)""").find(lineTrim)?.let { m ->
                            groupHashPrefix[m.groupValues[1].toIntOrNull() ?: return@let] =
                                m.groupValues[2].trimEnd('.')
                        }
                        Regex("""\[ГРУППА #(\d+)\] Ошибка кредов: (.+)""").find(lineTrim)?.let { m ->
                            if (tunnelReady.value) {
                                resolveHashForGroup(m.groupValues[1].toIntOrNull() ?: return@let)?.let { hash ->
                                    HashFailureReporter.report(scope, hash, "creds_failed", m.groupValues[2])
                                }
                            }
                        }
                        if (lineTrim.contains("[VK Auth] Failed")) {
                            Regex("""\[STREAM (\d+)\]""").find(lineTrim)?.let { m ->
                                val gid = (m.groupValues[1].toIntOrNull() ?: return@let) / 100
                                if (gid > 0) {
                                    resolveHashForGroup(gid)?.let { hash ->
                                        HashFailureReporter.report(scope, hash, "vk_auth_failed", lineTrim)
                                    }
                                }
                            }
                        }
                        if (
                            tunnelReady.value &&
                            (lineTrim.contains("хеш мёртв", true) ||
                                lineTrim.contains("call not found", true))
                        ) {
                            val hashHint = Regex("""(?:хеш|hash):\s*(\S+)""", RegexOption.IGNORE_CASE)
                                .find(lineTrim)?.groupValues?.getOrNull(1)
                                ?: sessionVkHashes.firstOrNull()
                            hashHint?.let { h ->
                                HashFailureReporter.report(scope, h, "hash_dead", lineTrim)
                            }
                        }
                    }

                    val isError = lineTrim.contains("Ошибка", true) ||
                        lineTrim.contains("error", true) ||
                        lineTrim.contains("FAIL", true) ||
                        lineTrim.contains("timeout", true) ||
                        lineTrim.contains("refused", true)

                    when {
                        lineTrim.contains("[КАПЧА] AUTO:") -> {
                            val text = lineTrim.substringAfter("[КАПЧА] AUTO:").trim()
                            updateLog("captcha_auto_${text.take(12).hashCode()}", "[КАПЧА AUTO] $text", 5, isError)
                        }
                        lineTrim.contains("[КАПЧА] RJS:") -> {
                            val text = lineTrim.substringAfter("[КАПЧА] RJS:").trim()
                            updateLog("captcha_rjs_${text.take(12).hashCode()}", "[КАПЧА RJS] $text", 5)
                        }
                        lineTrim.contains("[КАПЧА] WBV:") -> {
                            val text = lineTrim.substringAfter("[КАПЧА] WBV:").trim()
                            updateLog("captcha_wv_${text.take(12).hashCode()}", "[КАПЧА WBV] $text", 5, isError)
                        }
                        lineTrim.contains("Старт") || lineTrim.contains("Ожидайте") ->
                            updateLog("creds_start", "[ВК] Получение учётных данных…", 2)
                        lineTrim.contains("Креды OK") || lineTrim.contains("Первые креды") ->
                            updateLog("creds_ok", "[ВК] Учётные данные проверены ✓", 2)
                        lineTrim.contains("Решаю VK Smart Captcha") ->
                            updateLog("captcha_start", "[КАПЧА] Решение капчи…", 5)
                        lineTrim.contains("Smart Captcha решена") ->
                            updateLog("captcha_done", "[КАПЧА] Капча решена ✓", 5)
                        lineTrim.contains("[WRAP]") ->
                            updateLog("wrap_status", "[WRAP] ${lineTrim.substringAfter("[WRAP]").trim()}", 1)
                        lineTrim.contains("[TURN]") -> {
                            val text = lineTrim.substringAfter("[TURN]").trim()
                            updateLog("turn_${text.take(24).hashCode()}", "[TURN] $text", 2, isError)
                        }
                        lineTrim.contains("Relay:") || lineTrim.contains("[DTLS] Рукопожатие") ->
                            updateLog("dtls_start", "[DTLS] Рукопожатие…", 1)
                        lineTrim.contains("DTLS ОК") || lineTrim.contains("Соединение установлено ✓") ->
                            updateLog("dtls_ok", "[DTLS] Соединение установлено ✓", 1)
                        lineTrim.contains("[READY]") || lineTrim.contains("Активна ✓") -> {
                            updateLog("ready_line", "[READY] Туннель готов ✓", 2)
                            if (!tunnelReady.value) tryApplyWireGuardUp()
                        }
                        isError -> {
                            val errorKey = when {
                                lineTrim.contains("connection refused") -> "err_conn_refused"
                                lineTrim.contains("timeout") -> "err_timeout"
                                else -> "general_error_${lineTrim.take(12).hashCode()}"
                            }
                            updateLog(errorKey, lineTrim, 99, true)
                        }
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
                            if (configStr.isNotBlank()) scheduleWireGuardApply(configStr)
                        } else if (line.contains("║")) {
                            val content = line.replace("║", "").trim()
                            if (content.isNotEmpty()) configBuilder.appendLine(content)
                        }
                        return@forEachLine
                    }

                    if (lineTrim.contains("[КОНФИГ]") && lineTrim.contains("Сохранён")) {
                        wgConfigPending = true
                        scope.launch {
                            delay(400)
                            readConfFile(lastContext)?.let { scheduleWireGuardApply(it) }
                        }
                        return@forEachLine
                    }
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                val msg = e.message.orEmpty()
                if (process?.isAlive == true && msg.contains("Stream closed", true)) {
                    return@launch
                }
                if (!msg.contains("interrupted", true)) {
                    updateLog("sys_error", "Системная ошибка: $msg", 99, true)
                }
            } finally {
                val proc = process
                val alive = proc?.isAlive == true
                if (!alive && !tunnelReady.value) {
                    running.value = false
                }
                if (!alive) process = null
            }
        }
    }

    private fun readConfFile(context: Context?): String? {
        if (context == null) return null
        for (name in listOf("wg-turn.conf", "wg.conf")) {
            val f = File(context.filesDir, name)
            if (f.exists() && f.length() > 20) {
                val text = runCatching { f.readText().trim() }.getOrNull()
                if (!text.isNullOrBlank() && text.contains("[Interface]")) return text
            }
        }
        return null
    }

    private fun resolveHashForGroup(groupId: Int): String? {
        groupHashPrefix[groupId]?.let { prefix ->
            sessionVkHashes.find { it.startsWith(prefix) }?.let { return it }
            if (prefix.length >= 6) return prefix
        }
        if (sessionVkHashes.isEmpty()) return null
        return sessionVkHashes[(groupId - 1).coerceAtLeast(0) % sessionVkHashes.size]
    }

    private fun mobileApiRouteEnabled(): Boolean {
        val ctx = lastContext ?: return false
        return !isBootstrapMode &&
            SilentRepository.APP_EXCLUDED_FROM_VPN &&
            VpnNetworkHelper.isOnMobileData(ctx)
    }

    /** После Wi‑Fi↔LTE / восстановления сети — обновить AllowedIPs (mobile API route). */
    fun reapplyWireGuardForNetworkChange(context: Context) {
        if (!tunnelReady.value || isBootstrapMode || apiOverlayActive) return
        val config = lastWgConfig ?: return
        lastContext = context.applicationContext
        scope.launch {
            wgApplyMutex.withLock {
                if (!tunnelReady.value || isBootstrapMode || apiOverlayActive) return@withLock
                runCatching {
                    withContext(NonCancellable + Dispatchers.Main) {
                        wgHelper?.startTunnel(
                            config,
                            wgExcludeIps.toList(),
                            isBootstrap = false,
                            mobileApiRoute = mobileApiRouteEnabled(),
                        )
                    }
                    updateLog("wg_network_reload", "WireGuard: маршруты после смены сети", 2)
                }.onFailure { e ->
                    DebugLog.w("WdttTunnel", "wg network reload: ${e.message}")
                }
            }
        }
    }

    private fun applyWireGuard(configStr: String, forceReapply: Boolean = false) {
        val normalized = configStr.trim()
        if (normalized.isBlank()) return
        if (!forceReapply && tunnelReady.value) return
        if (!forceReapply && normalized == lastWgConfig && tunnelReady.value) return
        bootstrapFallbackJob?.cancel()
        if (wgApplyJob?.isActive == true) return
        wgApplyJob = scope.launch {
            wgApplyMutex.withLock {
                if (!forceReapply && tunnelReady.value) return@withLock
                if (!forceReapply && normalized == lastWgConfig && tunnelReady.value) return@withLock
                lastWgConfig = normalized
                try {
                    withContext(NonCancellable + Dispatchers.Main) {
                        wgHelper?.startTunnel(
                            normalized,
                            wgExcludeIps.toList(),
                            isBootstrap = isBootstrapMode,
                            mobileApiRoute = mobileApiRouteEnabled(),
                        )
                    }
                    tunnelReady.value = true
                    wgConfigPending = false
                    confPollJob?.cancel()
                    wgConfigRetryJob?.cancel()
                    updateLog("wg_up", "WireGuard UP ✓", 2)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (tunnelReady.value) return@withLock
                    lastError.value = "WireGuard: ${e.message}"
                    updateLog("vpn_start_error", "Ошибка WireGuard: ${e.message}", 99, true)
                    stop()
                }
            }
        }
    }

    private fun handleCriticalError(message: String) {
        updateLog("circuit_breaker", "[СТОП] $message", 99, true)
        lastError.value = message
        stop()
    }

    private fun startWatchdog(context: Context, params: Params) {
        watchdogJob?.cancel()
        watchdogJob = scope.launch {
            var zeroWorkersSince = 0L
            var lastRampWorkers = -1
            var rampStuckSince = 0L
            delay(10_000)
            while (isActive && running.value) {
                val proc = process
                if (proc == null || !proc.isAlive) {
                    updateLog("watchdog", "⚠ Процесс упал — перезапуск", 50, true)
                    activeWorkers.value = 0
                    killProcess()
                    delay(2000)
                    if (running.value) start(context, params, isSwitching = true)
                    return@launch
                }
                val workers = activeWorkers.value
                val totalWorkers = params.workers
                if (
                    totalWorkers > workers &&
                    workers > 0 &&
                    tunnelReady.value &&
                    !ManlCaptchaWebViewManager.isCaptchaPending
                ) {
                    if (workers != lastRampWorkers) {
                        lastRampWorkers = workers
                        rampStuckSince = System.currentTimeMillis()
                    } else if (
                        rampStuckSince > 0L &&
                        System.currentTimeMillis() - rampStuckSince > 75_000L
                    ) {
                        if (captchaInProgress && captchaSolveJob?.isActive != true) {
                            updateLog("captcha_stale", "[КАПЧА] Сброс зависшей капчи — повтор", 5, true)
                            captchaInProgress = false
                            captchaManualInProgress = false
                            captchaSolveJob?.cancel()
                            CaptchaWebViewManager.cancelCurrentSolve()
                            rampStuckSince = System.currentTimeMillis()
                        } else if (!captchaInProgress && !captchaManualInProgress) {
                            updateLog(
                                "ramp_stuck",
                                "⚠ Воркеры $workers/$totalWorkers — ждём капчу VK (группы 2+)",
                                50,
                                true,
                            )
                            rampStuckSince = System.currentTimeMillis()
                        }
                    }
                } else {
                    lastRampWorkers = workers
                    rampStuckSince = 0L
                }
                if (workers <= 0) {
                    if (zeroWorkersSince == 0L) zeroWorkersSince = System.currentTimeMillis()
                    else if (
                        wrapAuthTimeoutCount >= 3 &&
                        processStartedAtMs > 0L &&
                        System.currentTimeMillis() - processStartedAtMs > 30_000 &&
                        lastActiveAtMs == 0L &&
                        !ManlCaptchaWebViewManager.isCaptchaPending
                    ) {
                        handleCriticalError("🔒 Неверный пароль или несовместимый WRAP")
                        return@launch
                    } else if (
                        System.currentTimeMillis() - zeroWorkersSince > 180_000 &&
                        !ManlCaptchaWebViewManager.isCaptchaPending
                    ) {
                        sessionVkHashes.firstOrNull()?.let { h ->
                            HashFailureReporter.report(
                                scope,
                                h,
                                "no_connections",
                                "0 active workers for 180s",
                            )
                        }
                        updateLog("watchdog_zombie", "⚠ 0 воркеров 90с — перезапуск", 50, true)
                        killProcess()
                        delay(2000)
                        if (running.value) start(context, params, isSwitching = true)
                        return@launch
                    }
                } else {
                    zeroWorkersSince = 0L
                }
                delay(5_000)
            }
        }
    }

    fun restartTransport(forceNetwork: Boolean = false) {
        if (!forceNetwork) {
            val elapsed = System.currentTimeMillis() - processStartedAtMs
            if (processStartedAtMs > 0L && elapsed < NETWORK_RESTART_GRACE_MS) return
        }
        if (isNetworkRecoverySuppressed()) return
        if (!tunnelReady.value) return
        val params = lastParams ?: return
        val ctx = lastContext ?: return
        updateLog("network_restart", "[СЕТЬ] Перезапуск транспорта", 50)
        killProcess()
        scope.launch {
            delay(1500)
            start(ctx, params, isSwitching = true)
        }
    }

    /** Явное восстановление после смены сети / звонка — без grace libclient. */
    fun restartTransportAfterNetwork() = restartTransport(forceNetwork = true)

    /**
     * Новые хеши с сервера — перезапуск libclient без снятия WireGuard.
     * Только при стабильном туннеле, не во время капчи/ramp-up.
     */
    fun applyUpdatedVkHashes(context: Context, hashes: List<String>): Boolean {
        if (isBootstrapMode) return false
        if (!tunnelReady.value || !running.value) return false
        if (isWorkerRampUpActive()) return false
        if (isCaptchaInProgress() || ManlCaptchaWebViewManager.isCaptchaPending) return false
        if (activeWorkers.value <= 0) return false
        val params = lastParams ?: return false
        val normalized = hashes.map { it.trim() }.filter { it.isNotBlank() }.distinct()
            .take(HashChannelHelper.MAX_HASHES)
        if (normalized.isEmpty()) return false
        val current = params.vkHashes.map { it.trim() }.filter { it.isNotBlank() }
        if (normalized.toSet() == current.toSet()) return false
        val workers = HashChannelHelper.workersForLibclient(
            params.workers,
            normalized.size.coerceIn(1, HashChannelHelper.MAX_HASHES),
        )
        val newParams = params.copy(
            vkHashes = normalized,
            activeHashCount = normalized.size,
            workers = workers,
        )
        lastParams = newParams
        updateLog("hash_update", "Обновление хешей с сервера (${normalized.size})", 2)
        killProcess()
        scope.launch {
            delay(2000)
            if (running.value || tunnelReady.value) {
                start(context.applicationContext, newParams, isSwitching = true)
            }
        }
        return true
    }

    fun pause() {
        if (!running.value) return
        killProcess()
        activeWorkers.value = 0
    }

    fun resume() {
        val params = lastParams ?: return
        val ctx = lastContext ?: return
        if (running.value && process?.isAlive == true) return
        running.value = true
        scope.launch { start(ctx, params, isSwitching = true) }
    }

    fun isCaptchaInProgress(): Boolean = captchaInProgress
    fun isCaptchaManualInProgress(): Boolean = captchaManualInProgress

    fun lastWgAddress(): String? {
        val cfg = lastWgConfig ?: return null
        return Regex("""(?m)^Address\s*=\s*(\S+)""").find(cfg)?.groupValues?.getOrNull(1)
    }

    fun tunnelApiBase(): String = "http://${SilentRepository.WG_TUNNEL_GATEWAY}:8000"

    fun isBootstrapMode(): Boolean = isBootstrapMode
    fun lastParams(): Params? = lastParams

    fun wgConfigSettled(): Boolean = tunnelReady.value
    suspend fun awaitWgConfigSettled(timeoutMs: Long = 8000L) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (tunnelReady.value) return
            delay(100)
        }
    }

    fun isWorkerRampUpActive(): Boolean {
        if (!running.value || !tunnelReady.value) return false
        val total = lastParams?.workers ?: return false
        return activeWorkers.value in 1 until total
    }

    fun isApiOverlayActive(): Boolean = apiOverlayActive
    fun isNetworkRecoverySuppressed(): Boolean {
        if (apiOverlayActive || suppressNetworkRecovery || (wgHelper?.isWgTransitionActive() == true)) {
            return true
        }
        if (wgApplyJob?.isActive == true || wgApplyScheduled) return true
        val sinceOverlay = System.currentTimeMillis() - lastOverlayEndedMs
        if (lastOverlayEndedMs > 0L && sinceOverlay < 4_000L) return true
        return false
    }

    fun prepareForShutdown() {
        overlayRestoreSuppressed = true
    }

    /** WG поднят — VPN включён; воркеры могут ещё набираться. */
    fun isInternetReady(): Boolean = tunnelReady.value && running.value

    fun isTransportHealthy(): Boolean {
        if (!tunnelReady.value) return false
        val proc = process ?: return false
        return proc.isAlive && activeWorkers.value >= 1
    }

    /** Долго нет активных воркеров при живом процессе — вероятно «завис» после doze/смены сети. */
    fun isTransportStale(thresholdMs: Long): Boolean {
        if (!tunnelReady.value || !running.value) return false
        val proc = process ?: return false
        if (!proc.isAlive) return false
        val last = lastActiveAtMs
        if (last <= 0L) return false
        return activeWorkers.value <= 0 && System.currentTimeMillis() - last > thresholdMs
    }

    private fun needsWgOverlayReload(): Boolean = SilentRepository.APP_EXCLUDED_FROM_VPN

    suspend fun <T> withApiOverlay(block: suspend () -> T): T {
        if (overlayRestoreSuppressed) error("VPN API overlay suppressed")
        if (!needsWgOverlayReload()) {
            return block()
        }
        if (!isBootstrapMode) return withApiOverlayBrief(block, allowDuringRampUp = false)
        if (!running.value || apiOverlayActive) return block()
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            suppressNetworkRecovery = true
            updateLog("overlay_on", "API overlay ON (bootstrap)", 50)
            helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            delay(overlayEnterDelayMs)
            try {
                block()
            } finally {
                if (apiOverlayActive) {
                    updateLog("overlay_off", "API overlay OFF", 50)
                    helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = false, mobileApiRoute = mobileApiRouteEnabled())
                    apiOverlayActive = false
                    lastOverlayEndedMs = System.currentTimeMillis()
                }
                suppressNetworkRecovery = false
            }
        }
    }

    suspend fun <T> withApiOverlayForDownload(block: suspend () -> T): T {
        if (!needsWgOverlayReload()) return block()
        if (!running.value) return block()
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            if (apiOverlayActive) return@withLock block()
            suppressNetworkRecovery = true
            helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            delay(overlayEnterDelayMs)
            try {
                block()
            } finally {
                if (apiOverlayActive) {
                    helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = false, mobileApiRoute = mobileApiRouteEnabled())
                    apiOverlayActive = false
                    lastOverlayEndedMs = System.currentTimeMillis()
                }
                suppressNetworkRecovery = false
            }
        }
    }

    suspend fun <T> withApiOverlayBrief(
        block: suspend () -> T,
        allowDuringRampUp: Boolean = false,
    ): T {
        if (overlayRestoreSuppressed) error("VPN API overlay suppressed")
        if (!needsWgOverlayReload()) return block()
        if (!running.value) return block()
        if (isWorkerRampUpActive() && !allowDuringRampUp) {
            throw ApiOverlayBlockedException("overlay blocked during ramp-up")
        }
        if (!allowDuringRampUp && !apiOverlayActive) {
            val since = System.currentTimeMillis() - lastOverlayEndedMs
            if (lastOverlayEndedMs > 0L && since < minOverlayIntervalMs) {
                val waitMs = minOverlayIntervalMs - since
                updateLog("overlay_throttle", "API overlay throttled (${since}ms), wait ${waitMs}ms", 50)
                delay(waitMs)
            }
        }
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            if (apiOverlayActive) return@withLock block()
            suppressNetworkRecovery = true
            updateLog("overlay_on", "API overlay brief ON (10.66.66.0/24)", 50)
            helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            delay(if (allowDuringRampUp) 350L else overlayEnterDelayMs)
            try {
                block()
            } finally {
                // NonCancellable: restore overlay даже при таймауте/отмене вызова (иначе флаги залипнут).
                withContext(NonCancellable) {
                    if (apiOverlayActive) {
                        updateLog("overlay_off", "API overlay brief OFF", 50)
                        runCatching {
                            helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = false, mobileApiRoute = mobileApiRouteEnabled())
                        }
                        apiOverlayActive = false
                        lastOverlayEndedMs = System.currentTimeMillis()
                    }
                    suppressNetworkRecovery = false
                }
            }
        }
    }

    fun ensureApiOverlayOff() {
        if (overlayRestoreSuppressed || !apiOverlayActive || !needsWgOverlayReload()) {
            apiOverlayActive = false
            return
        }
        val config = lastWgConfig ?: run { apiOverlayActive = false; return }
        val helper = wgHelper ?: run { apiOverlayActive = false; return }
        scope.launch {
            wgApplyMutex.withLock {
                if (!apiOverlayActive) return@withLock
                helper.startTunnel(config, wgExcludeIps.toList(), isBootstrapMode, apiOverlayMode = false, mobileApiRoute = mobileApiRouteEnabled())
                apiOverlayActive = false
            }
        }
    }

    /** После появления TURN IP — расширить маршруты bootstrap (0.0.0.0/0 − TURN) для браузеров/почты. */
    private fun reloadBootstrapAllowedIps() {
        if (!isBootstrapMode || !tunnelReady.value || apiOverlayActive) return
        val config = lastWgConfig ?: return
        if (wgApplyJob?.isActive == true) return
        wgApplyJob = scope.launch {
            wgApplyMutex.withLock {
                if (!isBootstrapMode || !tunnelReady.value || apiOverlayActive) return@withLock
                try {
                    withContext(NonCancellable + Dispatchers.Main) {
                        wgHelper?.startTunnel(config, wgExcludeIps.toList(), isBootstrap = true)
                    }
                    updateLog("bootstrap_routes", "Bootstrap: маршруты обновлены (TURN вне VPN)", 2)
                } catch (e: Exception) {
                    DebugLog.w("WdttTunnel", "bootstrap route reload: ${e.message}")
                }
            }
        }
    }

    fun reloadWireGuard(context: Context) {
        if (!tunnelReady.value) return
        val config = lastWgConfig ?: return
        lastContext = context.applicationContext
        scope.launch {
            wgHelper?.stopTunnel()
            delay(200)
            withContext(Dispatchers.Main) {
                wgHelper?.startTunnel(
                    config,
                    wgExcludeIps.toList(),
                    isBootstrap = isBootstrapMode,
                    mobileApiRoute = mobileApiRouteEnabled(),
                )
            }
        }
    }

    private fun killProcess() {
        bootstrapFallbackJob?.cancel()
        mainWgFallbackJob?.cancel()
        confPollJob?.cancel()
        watchdogJob?.cancel()
        readerJob?.cancel()
        val proc = process
        process = null
        if (proc != null) {
            runCatching { proc.destroy() }
            runCatching { proc.waitFor(500, java.util.concurrent.TimeUnit.MILLISECONDS) }
            if (proc.isAlive) runCatching { proc.destroyForcibly() }
        }
    }

    fun stop() {
        scope.launch {
            startStopMutex.withLock { stopInternal() }
        }
    }

    suspend fun stopAndAwait() {
        startStopMutex.withLock { stopInternal() }
    }

    fun clearStaleSession() {
        running.value = false
        tunnelReady.value = false
        activeWorkers.value = 0
        stats.value = ""
        lastError.value = null
    }

    private suspend fun stopInternal() {
        overlayRestoreSuppressed = true
        apiOverlayActive = false
        suppressNetworkRecovery = false
        wgApplyJob?.cancel()
        wgApplyScheduled = false
        cancelAllCaptchaSolvers()
        withContext(NonCancellable + Dispatchers.IO) {
            TunnelApiProxy.stopAndAwait()
            killProcess()
            wgHelper?.stopTunnel()
            CaptchaWebViewManager.onTunnelStop()
            ManlCaptchaWebViewManager.cancelCaptcha()
            lastContext = null
            lastParams = null
            lastWgConfig = null
            deferredApiWgConfig = null
            wgApplyJob?.cancel()
            running.value = false
            tunnelReady.value = false
            activeWorkers.value = 0
            stats.value = ""
            lastError.value = null
        }
    }

    private fun scheduleCaptchaSolve(parts: List<String>) {
        if (captchaManualInProgress || ManlCaptchaWebViewManager.isCaptchaPending) {
            lastContext?.let { ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(it) }
            return
        }
        if (captchaInProgress) {
            if (captchaSolveJob?.isActive == true) return
            captchaInProgress = false
            captchaManualInProgress = false
        }
        // Одна капча на все потоки (reference) — иначе 36× параллельно ломает VK API.
        val requestMode = when (parts.size) {
            3 -> parts[0].lowercase()
            else -> "selected"
        }
        val redirectUri = when (parts.size) {
            3 -> parts[1]
            2 -> parts[0]
            else -> return
        }
        val sessionToken = when (parts.size) {
            3 -> parts[2]
            2 -> parts[1]
            else -> return
        }
        val now = System.currentTimeMillis()
        if (requestMode == "auto" && captchaInProgress &&
            redirectUri == lastCaptchaRedirectUri &&
            now - lastCaptchaScheduledMs < 30_000L
        ) {
            return
        }
        lastCaptchaRedirectUri = redirectUri
        lastCaptchaScheduledMs = now
        captchaInProgress = true
        captchaSolveJob?.cancel()
        CaptchaWebViewManager.cancelCurrentSolve()
        val session = captchaSession.incrementAndGet()
        captchaSolveJob = scope.launch {
            try {
                withTimeout(90_000L) {
                    handleCaptchaSolve(session, requestMode, redirectUri, sessionToken)
                }
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                if (session == captchaSession.get()) {
                    updateLog("captcha_timeout", "[КАПЧА] Таймаут 90с — повтор", 5, true)
                    writeCaptchaResult(session, "error:captcha timeout")
                    captchaInProgress = false
                    captchaManualInProgress = false
                }
            }
        }
    }

    private fun cancelAllCaptchaSolvers() {
        captchaSession.incrementAndGet()
        captchaInProgress = false
        captchaManualInProgress = false
        captchaSolveJob?.cancel()
        CaptchaWebViewManager.cancelCurrentSolve()
        ManlCaptchaWebViewManager.cancelCaptcha()
    }

    private suspend fun handleCaptchaSolve(
        session: Int,
        requestMode: String,
        redirectUri: String,
        sessionToken: String,
    ) {
        val ctx = lastContext ?: run {
            writeCaptchaResult(session, "error:context is null")
            return
        }
        captchaInProgress = true
        captchaManualInProgress = requestMode == "manual"
        try {
            val token = when (requestMode) {
                "manual" -> ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                else -> solveAutoWebViewCaptcha(ctx, redirectUri, sessionToken)
            }
            if (session != captchaSession.get()) return
            updateLog("captcha_solved", "[КАПЧА] Решена ✓", 5)
            writeCaptchaResult(session, token)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            if (session == captchaSession.get()) {
                updateLog("captcha_err", "[КАПЧА] ${e.message}", 5, true)
                writeCaptchaResult(session, "error:${e.message ?: "unknown"}")
            }
        } finally {
            if (session == captchaSession.get()) {
                captchaInProgress = false
                captchaManualInProgress = false
            }
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
                    captchaManualInProgress = true
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
                throw e
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                if (attempt == 1) {
                    captchaManualInProgress = true
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
            }
        }
        captchaManualInProgress = true
        return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
    }

    private fun writeCaptchaResult(session: Int, result: String) {
        if (session != captchaSession.get()) return
        val proc = process ?: return
        if (!proc.isAlive) return
        runCatching {
            proc.outputStream.write("CAPTCHA_RESULT|$result\n".toByteArray(Charsets.UTF_8))
            proc.outputStream.flush()
        }
    }
}
