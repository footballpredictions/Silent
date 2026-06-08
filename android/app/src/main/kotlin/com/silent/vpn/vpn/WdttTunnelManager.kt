package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.util.Log
import com.silent.vpn.data.HashChannelHelper
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.SessionTrace
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
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlin.coroutines.cancellation.CancellationException
import java.io.File
import java.util.concurrent.atomic.AtomicInteger

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
    private val startStopMutex = Mutex()
    private var apiOverlayDepth = 0
    @Volatile private var apiOverlayActive = false
    @Volatile private var suppressNetworkRecovery = false
    private var overlayHoldUntilMs = 0L
    private var overlayRestoreJob: Job? = null
    private val overlayHoldMs = 4_000L
    private val overlayEnterDelayMs = 800L
    private var appContext: Context? = null
    private var lastParams: Params? = null
    private var lastContext: Context? = null
    private var processStartedAtMs = 0L
    private var wrapAuthTimeoutCount = 0
    private var isSwitchingTransport = false
    private val wgExcludeIps = linkedSetOf<String>()
    private var captchaSolveJob: Job? = null
    private val captchaSession = AtomicInteger(0)
    @Volatile private var captchaInProgress = false
    @Volatile private var captchaManualInProgress = false
    private var lastCaptchaRedirectUri: String? = null
    private var lastCaptchaScheduledMs = 0L

    fun isCaptchaInProgress(): Boolean = captchaInProgress
    fun isCaptchaManualInProgress(): Boolean = captchaManualInProgress

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
    private var sessionVkHashes: List<String> = emptyList()
    private val groupHashPrefix = mutableMapOf<Int, String>()

    fun start(context: Context, params: Params, isSwitching: Boolean = false) {
        SessionTrace.enter(
            "WdttTunnelManager.start",
            "workers=${params.workers} hashes=${params.vkHashes.size} switching=$isSwitching bootstrap=${params.isBootstrap}",
        )
        scope.launch {
            startStopMutex.withLock {
                val ctx = context.applicationContext
                if (!isSwitching) {
                    stopInternal(keepWg = false)
                    lastError.value = null
                    tunnelReady.value = false
                    stats.value = "Ожидание данных…"
                    activeWorkers.value = 0
                    deferredApiWgConfig = null
                    wrapAuthTimeoutCount = 0
                    appliedConfigSource = 0
                    appliedConfigFingerprint = null
                    lastParams = params
                    lastContext = ctx
                    isBootstrapMode = params.isBootstrap
                    apiFallbackConfig = params.apiWgConfig?.trim()?.takeIf { it.contains("[Interface]") }
                    // Основной VPN: WG только из box/file libclient — без cached apply (иначе двойной UP).
                    if (params.isBootstrap && apiFallbackConfig != null) {
                        deferredApiWgConfig = apiFallbackConfig
                    }
                    CaptchaWebViewManager.onTunnelStart(context)
                } else {
                overlayRestoreJob?.cancel()
                apiOverlayDepth = 0
                apiOverlayActive = false
                killProcess()
                activeWorkers.value = 0
                stats.value = "Ожидание данных…"
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
                    return@withLock
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
                    return@withLock
                }
                if (params.wdttPassword.isBlank()) {
                    lastError.value = "Пароль WDTT не задан"
                    DebugLog.e(TAG, lastError.value!!)
                    return@withLock
                }

                sessionVkHashes = hashList
                if (!isSwitching) groupHashPrefix.clear()

                if (!isSwitching) {
                    wgExcludeIps.clear()
                }

                DebugLog.i(
                    TAG,
                    "start peer=${params.serverIp}:${params.serverPort} n=$workers hashes=${hashList.size} switching=$isSwitching",
                )

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
                    systemDnsForLibclient(context)?.let { dns ->
                        add("-sys-dns")
                        add(dns)
                    }
                }

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
                    return@withLock
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
    }

    private fun sanitizeCaptchaMode(mode: String): String = when (mode.lowercase()) {
        "rjs", "wv", "auto" -> mode.lowercase()
        else -> "auto"
    }

    /** DNS оператора с LinkProperties — fallback для libclient на LTE с белыми списками. */
    private fun systemDnsForLibclient(context: Context): String? {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager ?: return null
        val servers = cm.getLinkProperties(cm.activeNetwork)?.dnsServers ?: return null
        return servers.mapNotNull { addr ->
            addr.hostAddress?.takeIf { it.isNotBlank() }?.let { host ->
                if (host.contains(':')) host else "$host:53"
            }
        }.distinct().joinToString(",").takeIf { it.isNotBlank() }
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
        if (!isBootstrapMode) return
        if (activeWorkers.value < 1 || appliedConfigSource > 0) return
        val cfg = deferredApiWgConfig ?: apiFallbackConfig ?: return
        deferredApiWgConfig = null
        if (isBootstrapMode) {
            DebugLog.i(TAG, "WireGuard API apply after ${activeWorkers.value} workers (bootstrap)")
            applyWireGuard(cfg, source = 1)
        } else {
            DebugLog.i(TAG, "WireGuard cached apply after ${activeWorkers.value} workers (main)")
            applyWireGuard(cfg, source = 2)
        }
    }

    private fun resolveHashForGroup(groupId: Int): String? {
        groupHashPrefix[groupId]?.let { prefix ->
            sessionVkHashes.find { it.startsWith(prefix) }?.let { return it }
            if (prefix.length >= 6) return prefix
        }
        if (sessionVkHashes.isEmpty()) return null
        val idx = (groupId - 1).coerceAtLeast(0)
        return sessionVkHashes[idx % sessionVkHashes.size]
    }

    private fun hashTargetsForWorkerFatal(): List<String> {
        val fromGroups = groupHashPrefix.values.mapNotNull { prefix ->
            sessionVkHashes.find { it.startsWith(prefix) } ?: prefix.takeIf { it.length >= 6 }
        }.distinct()
        return fromGroups.ifEmpty { sessionVkHashes.take(1) }
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
                    val important = lineTrim.contains("[СТАТИСТИКА]") ||
                        lineTrim.contains("FATAL") ||
                        lineTrim.contains("ГРУППА #") ||
                        lineTrim.contains("[VK Auth]") ||
                        lineTrim.contains("Ошибка кредов") ||
                        lineTrim.contains("Креды OK") ||
                        lineTrim.contains("[КАПЧА]") ||
                        lineTrim.contains("[Captcha]") ||
                        lineTrim.contains("[READY]") ||
                        lineTrim.contains("API overlay") ||
                        lineTrim.startsWith("CAPTCHA_SOLVE|") ||
                        lineTrim.contains("Ошибка кредов") ||
                        lineTrim.contains("WireGuard")
                    if (important) {
                        DebugLog.i(TAG, lineTrim)
                    } else if (com.silent.vpn.BuildConfig.DEBUG) {
                        DebugLog.d(TAG, lineTrim)
                    }

                    if (lineTrim.startsWith("CAPTCHA_SOLVE|")) {
                        val payload = lineTrim.substringAfter("CAPTCHA_SOLVE|")
                        val parts = payload.split("|", limit = 3)
                        scheduleCaptchaSolve(parts)
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
                        val newActive = Regex("Активных:\\s*(\\d+)").find(msg)?.groupValues?.getOrNull(1)?.toIntOrNull()
                        val prevActive = activeWorkers.value
                        newActive?.let {
                            activeWorkers.value = it
                            if (it > 0) wrapAuthTimeoutCount = 0
                            if (prevActive < 1 && it >= 1) tryApplyDeferredApiWg()
                        }
                        return@forEachLine
                    }

                    Regex("""TURN UDP \(([\d.]+):\d+\)""").find(lineTrim)?.groupValues?.getOrNull(1)?.let { turnIp ->
                        if (isBootstrapMode && wgExcludeIps.add(turnIp)) {
                            DebugLog.i(TAG, "Bootstrap TURN IP excluded from WG: $turnIp")
                        }
                    }

                    if (!isBootstrapMode) {
                        Regex("""\[ГРУППА #(\d+)\] Запрос кредов \(хеш: (\S+)""").find(lineTrim)?.let { m ->
                            val gid = m.groupValues[1].toIntOrNull() ?: return@let
                            groupHashPrefix[gid] = m.groupValues[2].trimEnd('.')
                        }
                        Regex("""\[ГРУППА #(\d+)\] Ошибка кредов: (.+)""").find(lineTrim)?.let { m ->
                            val gid = m.groupValues[1].toIntOrNull() ?: return@let
                            if (tunnelReady.value) {
                                resolveHashForGroup(gid)?.let { hash ->
                                    HashFailureReporter.report(scope, hash, "creds_failed", m.groupValues[2])
                                }
                            }
                        }
                        if (lineTrim.contains("[VK Auth] Failed")) {
                            Regex("""\[STREAM (\d+)\]""").find(lineTrim)?.let { m ->
                                val streamId = m.groupValues[1].toIntOrNull() ?: return@let
                                val gid = streamId / 100
                                if (gid > 0) {
                                    resolveHashForGroup(gid)?.let { hash ->
                                        HashFailureReporter.report(scope, hash, "vk_auth_failed", lineTrim)
                                    }
                                }
                            }
                        }
                        Regex("""\[ВОРКЕР #\d+\] Фатальная ошибка: (.+)""").find(lineTrim)?.let { m ->
                            val err = m.groupValues[1]
                            if (err.contains("хеш мёртв", ignoreCase = true)) {
                                hashTargetsForWorkerFatal().forEach { hash ->
                                    HashFailureReporter.report(scope, hash, "hash_dead", err)
                                }
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
                val msg = e.message.orEmpty()
                if (msg.contains("interrupted", ignoreCase = true) || msg.contains("close()", ignoreCase = true)) {
                    DebugLog.d(TAG, "libclient reader stopped")
                } else if (running.value) {
                    Log.e(TAG, "Reader error", e)
                    DebugLog.e(TAG, "Reader error", e)
                }
            } finally {
                val proc = process
                val exitCode = runCatching { proc?.exitValue() }.getOrNull()
                if (exitCode != null) {
                    DebugLog.w(TAG, "libclient exited code=$exitCode ready=${tunnelReady.value}")
                    activeWorkers.value = 0
                    if (tunnelReady.value && lastParams != null && lastContext != null && running.value) {
                        val ctx = lastContext!!
                        val params = lastParams!!
                        scope.launch {
                            delay(2500)
                            if (process == null && running.value && tunnelReady.value) {
                                DebugLog.i(TAG, "libclient упал при активном WG — перезапуск транспорта")
                                start(ctx, params, isSwitching = true)
                            }
                        }
                    }
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
                    SessionTrace.mark("WdttTunnelManager.tunnelReady", "workers=${activeWorkers.value}")
                    DebugLog.i(TAG, "tunnelReady: WG UP + ${activeWorkers.value} active workers")
                    return@launch
                }
            }
        }
    }

    private fun wgExcludeForTunnel(): List<String> =
        if (isBootstrapMode) wgExcludeIps.toList() else emptyList()

    /** source: 1=api, 2=box log, 3=wg-turn.conf — higher is better */
    private fun applyWireGuard(configStr: String, source: Int = 1) {
        val normalized = configStr.trim()
        if (normalized.isBlank()) return
        if (!isBootstrapMode && activeWorkers.value < 1 && source == 1) {
            deferredApiWgConfig = normalized
            DebugLog.d(TAG, "defer WG API until WDTT workers ready")
            return
        }
        if (source == 1 && !isBootstrapMode) {
            deferredApiWgConfig = normalized
            DebugLog.d(TAG, "skip WG API on main VPN, wait libclient box/file")
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
                    wgHelper?.startTunnel(normalized, wgExcludeForTunnel(), isBootstrapMode)
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

    private var overlayRestoreSuppressed = false

    /** Перед отключением VPN — не восстанавливать полный туннель после overlay. */
    fun prepareForShutdown() {
        overlayRestoreSuppressed = true
        overlayRestoreJob?.cancel()
    }

    fun wgConfigSettled(): Boolean = appliedConfigSource >= 2

    /** Ждём финальный WG-конфиг (box/file), чтобы overlay API не гонялся с applyWireGuard. */
    suspend fun awaitWgConfigSettled(timeoutMs: Long = 8000L) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (appliedConfigSource >= 2 && activeWorkers.value >= 1 && wgHelper?.isTunnelUp() == true) {
                delay(250)
                return
            }
            delay(100)
        }
        DebugLog.w(TAG, "awaitWgConfigSettled: timeout (source=$appliedConfigSource)")
    }

    fun isBootstrapMode(): Boolean = isBootstrapMode

    fun lastParams(): Params? = lastParams

    /** libclient ещё набирает группы — overlay WG ломает VK creds (app в туннеле с /24). */
    fun isWorkerRampUpActive(): Boolean {
        if (!running.value || !tunnelReady.value) return false
        val total = lastParams?.workers ?: return false
        return activeWorkers.value < total
    }

    fun isApiOverlayActive(): Boolean = apiOverlayActive

    fun isNetworkRecoverySuppressed(): Boolean = apiOverlayActive || suppressNetworkRecovery

    class ApiOverlayBlockedException(message: String) : Exception(message)

    private var lastOverlayEndedMs = 0L
    private val minOverlayIntervalMs = 60_000L

    /**
     * Bootstrap: overlay WG для API.
     */
    suspend fun <T> withApiOverlay(block: suspend () -> T): T {
        if (!isBootstrapMode) {
            return withApiOverlayBrief(block, allowDuringRampUp = false)
        }
        if (!running.value) return block()
        if (apiOverlayActive) return block()
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            overlayRestoreJob?.cancel()
            DebugLog.i(TAG, "API overlay ON (bootstrap)")
            helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            apiOverlayDepth = 0
            delay(overlayEnterDelayMs)
            try {
                block()
            } finally {
                if (apiOverlayActive) {
                    DebugLog.i(TAG, "API overlay OFF (bootstrap)")
                    helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = false)
                    apiOverlayActive = false
                }
            }
        }
    }

    /**
     * Скачивание обновления: overlay держим на всё время HTTP (APK может быть большим).
     * Без throttle — иначе повторный tap через минуту после checkUpdate получает отказ.
     */
    suspend fun <T> withApiOverlayForDownload(block: suspend () -> T): T {
        if (!running.value) return block()
        if (isWorkerRampUpActive()) {
            throw ApiOverlayBlockedException(
                "overlay blocked during worker ramp-up (${activeWorkers.value}/${lastParams?.workers})",
            )
        }
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            if (apiOverlayActive) return@withLock block()
            overlayRestoreJob?.cancel()
            suppressNetworkRecovery = true
            DebugLog.i(TAG, "API overlay download ON (10.66.66.0/24)")
            helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            delay(overlayEnterDelayMs)
            try {
                block()
            } finally {
                suppressNetworkRecovery = false
                if (apiOverlayActive) {
                    DebugLog.i(TAG, "API overlay download OFF")
                    helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = false)
                    apiOverlayActive = false
                    lastOverlayEndedMs = System.currentTimeMillis()
                }
            }
        }
    }

    /**
     * Основной VPN: краткий overlay 10.66.66.0/24 — только HTTP к API, libclient/TURN мимо VPN.
     * @param allowDuringRampUp только для initial backend sync сразу после 1-й группы.
     */
    suspend fun <T> withApiOverlayBrief(
        block: suspend () -> T,
        allowDuringRampUp: Boolean = false,
    ): T {
        if (!running.value) return block()
        if (isWorkerRampUpActive() && !allowDuringRampUp) {
            throw ApiOverlayBlockedException(
                "overlay blocked during worker ramp-up (${activeWorkers.value}/${lastParams?.workers})",
            )
        }
        if (!allowDuringRampUp && !apiOverlayActive) {
            val since = System.currentTimeMillis() - lastOverlayEndedMs
            if (lastOverlayEndedMs > 0L && since < minOverlayIntervalMs) {
                val waitMs = minOverlayIntervalMs - since
                DebugLog.d(TAG, "API overlay throttled (${since}ms since last), wait ${waitMs}ms")
                delay(waitMs)
            }
        }
        val config = lastWgConfig ?: return block()
        val helper = wgHelper ?: return block()
        return wgApplyMutex.withLock {
            if (apiOverlayActive) return@withLock block()
            overlayRestoreJob?.cancel()
            suppressNetworkRecovery = true
            DebugLog.i(TAG, "API overlay brief ON (10.66.66.0/24)")
            helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = true)
            apiOverlayActive = true
            delay(if (allowDuringRampUp) 350L else overlayEnterDelayMs)
            try {
                block()
            } finally {
                suppressNetworkRecovery = false
                if (apiOverlayActive) {
                    DebugLog.i(TAG, "API overlay brief OFF")
                    helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = false)
                    apiOverlayActive = false
                    lastOverlayEndedMs = System.currentTimeMillis()
                }
            }
        }
    }

    /** Сброс overlay при disconnect / ошибке. */
    fun ensureApiOverlayOff() {
        overlayRestoreJob?.cancel()
        if (!apiOverlayActive) return
        val config = lastWgConfig ?: run { apiOverlayActive = false; return }
        val helper = wgHelper ?: run { apiOverlayActive = false; return }
        scope.launch {
            wgApplyMutex.withLock {
                if (!apiOverlayActive) return@withLock
                DebugLog.i(TAG, "API overlay force OFF")
                helper.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode, apiOverlayMode = false)
                apiOverlayActive = false
                apiOverlayDepth = 0
            }
        }
    }

    private fun scheduleOverlayRestore(config: String, helper: WireGuardHelper) {
        // Deprecated: overlay восстанавливается синхронно в withApiOverlay.finally
    }

    fun isInternetReady(): Boolean =
        tunnelReady.value && activeWorkers.value >= 1 && !lastWgAddress().isNullOrBlank() && appliedConfigSource > 0

    /** WG поднят, libclient жив, есть хотя бы один воркер. */
    fun isTransportHealthy(): Boolean {
        if (!tunnelReady.value || activeWorkers.value < 1) return false
        val proc = process ?: return false
        return proc.isAlive
    }

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
        SessionTrace.mark("WdttTunnelManager.stop")
        scope.launch {
            startStopMutex.withLock { stopInternal(keepWg = false) }
        }
    }

    suspend fun stopAndAwait() {
        startStopMutex.withLock { stopInternal(keepWg = false) }
    }

    /** После kill процесса — сброс Flow без stopInternal (плитка QS). */
    fun clearStaleSession() {
        SessionTrace.mark("WdttTunnelManager.clearStaleSession")
        running.value = false
        tunnelReady.value = false
        activeWorkers.value = 0
        stats.value = ""
        lastError.value = null
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
                wgHelper?.startTunnel(config, wgExcludeForTunnel(), isBootstrapMode)
            } catch (e: Exception) {
                lastError.value = "WireGuard: ${e.message}"
            }
        }
    }

    private suspend fun stopInternal(keepWg: Boolean) {
        overlayRestoreSuppressed = true
        ensureApiOverlayOff()
        cancelAllCaptchaSolvers()
        withContext(Dispatchers.IO) {
            overlayRestoreJob?.cancel()
            apiOverlayDepth = 0
            apiOverlayActive = false
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

    private fun scheduleCaptchaSolve(parts: List<String>) {
        val requestMode = when (parts.size) {
            3 -> parts[0].lowercase()
            else -> "selected"
        }
        val redirectUri = when (parts.size) {
            3 -> parts[1]
            2 -> parts[0]
            else -> return
        }
        val now = System.currentTimeMillis()

        // Ручная капча на экране — не сбрасывать повторными запросами от libclient.
        if (captchaManualInProgress || ManlCaptchaWebViewManager.isCaptchaPending) {
            if (requestMode == "auto") {
                DebugLog.w(TAG, "CAPTCHA auto skipped — manual WebView open")
                return
            }
            DebugLog.d(TAG, "CAPTCHA manual skipped — already open")
            appContext?.let { ManlCaptchaWebViewManager.checkAndShowPendingCaptcha(it) }
            return
        }
        // Auto ещё решается — не перезапускать (libclient шлёт retry каждые ~10 с).
        if (requestMode == "auto" && captchaInProgress &&
            redirectUri == lastCaptchaRedirectUri &&
            now - lastCaptchaScheduledMs < 30_000L
        ) {
            DebugLog.d(TAG, "CAPTCHA auto skipped — in progress")
            return
        }
        lastCaptchaRedirectUri = redirectUri
        lastCaptchaScheduledMs = now

        captchaSolveJob?.cancel()
        CaptchaWebViewManager.cancelCurrentSolve()
        val session = captchaSession.incrementAndGet()
        captchaSolveJob = scope.launch {
            when (parts.size) {
                3 -> handleCaptchaSolve(session, parts[0], parts[1], parts[2])
                2 -> handleCaptchaSolve(session, "selected", parts[0], parts[1])
                else -> writeCaptchaResultIfCurrent(session, "error:invalid CAPTCHA_SOLVE format")
            }
        }
    }

    private fun cancelAllCaptchaSolvers() {
        captchaSession.incrementAndGet()
        captchaInProgress = false
        captchaManualInProgress = false
        lastCaptchaRedirectUri = null
        captchaSolveJob?.cancel()
        captchaSolveJob = null
        CaptchaWebViewManager.cancelCurrentSolve()
        ManlCaptchaWebViewManager.cancelCaptcha()
    }

    private suspend fun handleCaptchaSolve(
        session: Int,
        requestMode: String,
        redirectUri: String,
        sessionToken: String,
    ) {
        val ctx = appContext ?: run {
            writeCaptchaResultIfCurrent(session, "error:context is null")
            return
        }
        DebugLog.i(TAG, "CAPTCHA solve mode=$requestMode session=$session")
        captchaInProgress = true
        captchaManualInProgress = requestMode == "manual"
        try {
            val token = when (requestMode.lowercase()) {
                "manual" -> ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                else -> solveAutoWebViewCaptcha(ctx, redirectUri, sessionToken)
            }
            if (!isCaptchaSessionCurrent(session)) {
                DebugLog.d(TAG, "CAPTCHA result ignored (superseded session=$session)")
                return
            }
            DebugLog.i(TAG, "CAPTCHA solved (${token.length} chars)")
            writeCaptchaResultIfCurrent(session, token)
        } catch (e: CancellationException) {
            if (isCaptchaSessionCurrent(session)) {
                DebugLog.d(TAG, "CAPTCHA cancelled session=$session")
            }
        } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
            if (!isCaptchaSessionCurrent(session)) return
            DebugLog.e(TAG, "CAPTCHA timeout session=$session")
            writeCaptchaResultIfCurrent(session, "error:timeout")
        } catch (e: Exception) {
            if (!isCaptchaSessionCurrent(session)) return
            DebugLog.e(TAG, "CAPTCHA failed: ${e.message}")
            writeCaptchaResultIfCurrent(session, "error:${e.message ?: "unknown"}")
        } finally {
            if (isCaptchaSessionCurrent(session)) {
                captchaInProgress = false
                captchaManualInProgress = false
            }
        }
    }

    private fun isCaptchaSessionCurrent(session: Int): Boolean = session == captchaSession.get()

    private fun writeCaptchaResultIfCurrent(session: Int, result: String) {
        if (!isCaptchaSessionCurrent(session)) {
            DebugLog.d(TAG, "CAPTCHA_RESULT skipped (stale session=$session)")
            return
        }
        writeCaptchaResult(result)
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
                    captchaManualInProgress = true
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
                throw e
            } catch (e: kotlinx.coroutines.TimeoutCancellationException) {
                if (attempt == 1) {
                    DebugLog.w(TAG, "CAPTCHA auto WBV timeout -> manual")
                    captchaManualInProgress = true
                    return ManlCaptchaWebViewManager.solveCaptchaAsync(ctx, redirectUri, sessionToken)
                }
            }
        }
        captchaManualInProgress = true
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
