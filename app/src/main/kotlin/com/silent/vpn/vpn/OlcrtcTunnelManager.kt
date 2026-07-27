package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.IpPrefix
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.system.OsConstants
import com.silent.vpn.BuildConfig
import com.silent.vpn.data.DnsPreset
import com.silent.vpn.data.SilentPrefs
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.policy.OlcrtcRecoveryPolicy
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.URLEncoder
import java.security.SecureRandom
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import android.util.Base64

/**
 * Debug-only: olcrtc cnc (SOCKS5). Старт неблокирующий — SOCKS ждём в фоне,
 * иначе SilentVpnService.onStartCommand зависает на main и UI «вечно подключается».
 */
object OlcrtcTunnelManager {
    data class Params(
        val provider: String,
        val room: String,
        val cryptoKey: String,
        val transport: String,
        val socksHost: String = "127.0.0.1",
        val socksPort: Int = 8808,
        /** Per-session SOCKS5 RFC1929 — без auth любой локальный процесс жжёт peer. */
        val socksUser: String = "",
        val socksPass: String = "",
        val isBootstrap: Boolean = false,
        /** LTE DPI: HTTP CONNECT к Улью, дальше meet.egovm.ru */
        val httpsProxy: String = "",
        /** WB Stream: JWT аккаунта (auth.token), не guest */
        val authToken: String = "",
    )

    private val _running = MutableStateFlow(false)
    val running: StateFlow<Boolean> = _running.asStateFlow()
    private val _tunnelReady = MutableStateFlow(false)
    val tunnelReady: StateFlow<Boolean> = _tunnelReady.asStateFlow()
    private val _lastError = MutableStateFlow<String?>(null)
    val lastError: StateFlow<String?> = _lastError.asStateFlow()

    private var olcrtcProc: Process? = null
    private var tunBridgeProc: Process? = null
    private var tunFd: ParcelFileDescriptor? = null
    private val starting = AtomicBoolean(false)

    fun isStarting(): Boolean = starting.get()
    @Volatile private var lastFailHint: String = ""
    /** ICE PeerConnection connected — можно поднимать hev full-tunnel. */
    @Volatile private var iceConnected = false
    /** Последний CONNECT JSON — для network/peer reconnect без UI. */
    @Volatile private var cachedConfigJson: String? = null
    @Volatile private var sessionDeadHandler: ((String) -> Unit)? = null
    @Volatile private var lastPeerDeadAtMs = 0L
    /** Recover/stop: старый watchExit не должен дергать peer_dead. */
    @Volatile private var suppressPeerDeadUntilMs = 0L
    /** Активные SOCKS-параметры — для health-probe из watchdog. */
    @Volatile private var activeParams: Params? = null
    /** Telemost/goolom сам переподключает PC — не убиваем процесс сразу на closed. */
    @Volatile private var peerClosedPending = false
    private var peerClosedGraceFuture: ScheduledFuture<*>? = null
    private val openStreamFailStreak = AtomicInteger(0)
    /** Последний успешный SOCKS tunnel (speedtest/Intermeter грузят peer — не SOCKS_DEAD). */
    @Volatile private var lastTunnelActivityMs = 0L
    private val scheduler = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "olcrtc-grace").apply { isDaemon = true }
    }
    /** Кэш OkHttp auth (room → file + expiry), чтобы reconnect был ближе к VK. */
    private data class PrefetchCache(val room: String, val file: File, val untilMs: Long)
    @Volatile private var telemostPrefetchCache: PrefetchCache? = null
    @Volatile private var wbPrefetchCache: PrefetchCache? = null
    private val worker = Executors.newSingleThreadExecutor { r ->
        Thread(r, "olcrtc-start").apply { isDaemon = true }
    }

    fun lastConfigJson(): String? = cachedConfigJson

    fun setSessionDeadHandler(handler: ((String) -> Unit)?) {
        sessionDeadHandler = handler
    }

    fun suppressPeerDeadFor(ms: Long) {
        suppressPeerDeadUntilMs = System.currentTimeMillis() + ms.coerceAtLeast(0L)
    }

    /** Были ли «tunnel to …» недавно — peer жив даже если gstatic probe таймаутится. */
    fun hasRecentTunnelTraffic(nowMs: Long = System.currentTimeMillis()): Boolean =
        OlcrtcRecoveryPolicy.hasRecentTunnelTraffic(lastTunnelActivityMs, nowMs)

    /** true если SOCKS dial к gstatic проходит (peer жив). */
    fun probeSocksHealthy(): Boolean {
        val p = activeParams ?: return false
        if (!_running.value) return false
        // При живом speedtest/Intermeter gstatic часто не успевает за 3.5с — не врём «мёртв».
        if (hasRecentTunnelTraffic()) return true
        return socksDialOnce(p, "www.gstatic.com", soTimeoutMs = 3_500)
    }

    private fun cancelPeerClosedGrace() {
        peerClosedGraceFuture?.cancel(false)
        peerClosedGraceFuture = null
        peerClosedPending = false
    }

    private fun clearPrefetchCaches() {
        if (!OlcrtcRecoveryPolicy.shouldInvalidatePrefetchOnStop()) return
        telemostPrefetchCache?.file?.let { runCatching { it.delete() } }
        wbPrefetchCache?.file?.let { runCatching { it.delete() } }
        telemostPrefetchCache = null
        wbPrefetchCache = null
    }

    /**
     * Telemost: PC closed часто с последующим internal reconnect.
     * Ждём [graceMs] — если снова Connected, restart не нужен.
     */
    private fun schedulePeerClosedGrace(reason: String, graceMs: Long = OlcrtcRecoveryPolicy.PEER_CLOSED_GRACE_MS) {
        if (!_running.value) return
        val now = System.currentTimeMillis()
        if (now < suppressPeerDeadUntilMs) {
            DebugLog.i("Olcrtc", "peer closed grace suppressed: $reason")
            return
        }
        if (peerClosedPending) return
        peerClosedPending = true
        iceConnected = false
        WdttTunnelManager.logUi(
            "olcrtc_pc_grace",
            "peer closed — ждём самовосстановление ${graceMs / 1000}с…",
            2,
        )
        peerClosedGraceFuture?.cancel(false)
        peerClosedGraceFuture = scheduler.schedule({
            try {
                if (
                    OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                        OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                            running = _running.value,
                            iceConnected = iceConnected,
                            socksHealthy = probeSocksHealthy(),
                            recentTunnelTraffic = hasRecentTunnelTraffic(),
                        ),
                    )
                ) {
                    peerClosedPending = false
                    notifyPeerDead(reason)
                } else {
                    peerClosedPending = false
                    if (!_running.value) return@schedule
                    when {
                        iceConnected -> {
                            WdttTunnelManager.logUi("olcrtc_pc_ok", "peer восстановился сам", 2)
                        }
                        probeSocksHealthy() -> {
                            iceConnected = true
                            WdttTunnelManager.logUi(
                                "olcrtc_pc_ok",
                                "peer closed, но SOCKS жив — без restart",
                                2,
                            )
                        }
                    }
                }
            } catch (e: Exception) {
                DebugLog.w("Olcrtc", "peer closed grace: ${e.message}")
                peerClosedPending = false
                notifyPeerDead(reason)
            }
        }, graceMs, TimeUnit.MILLISECONDS)
    }

    private fun onPeerConnectedAgain() {
        iceConnected = true
        openStreamFailStreak.set(0)
        if (peerClosedPending) {
            cancelPeerClosedGrace()
            WdttTunnelManager.logUi("olcrtc_pc_ok", "peer снова connected — без restart", 2)
        }
        if (_running.value && !_tunnelReady.value && probeSocksHealthy()) {
            _tunnelReady.value = true
        }
    }

    /**
     * Peer closed / process exit после ready → UI CONNECTING + SilentVpnService restart.
     * Дебаунс: один сигнал на волну EOF/closed.
     */
    private fun notifyPeerDead(reason: String) {
        if (!_running.value && !_tunnelReady.value) return
        val now = System.currentTimeMillis()
        if (now < suppressPeerDeadUntilMs) {
            DebugLog.i("Olcrtc", "peer dead suppressed: $reason")
            return
        }
        if (now - lastPeerDeadAtMs < 8_000L) return
        lastPeerDeadAtMs = now
        cancelPeerClosedGrace()
        val wasReady = _tunnelReady.value
        _tunnelReady.value = false
        iceConnected = false
        DebugLog.w("Olcrtc", "peer dead: $reason wasReady=$wasReady")
        WdttTunnelManager.logUi(
            "olcrtc_peer_dead",
            "связь оборвана ($reason) — переподключение…",
            2,
            isError = true,
        )
        sessionDeadHandler?.invoke(reason)
    }

    /** Per-stream EOF при живом peer — не красить весь лог красным. */
    private fun isTransientStreamNoise(line: String): Boolean {
        val l = line.lowercase()
        return l.contains("remote not ready") ||
            l.contains("connect failed: sid=") ||
            l.contains("openstream failed") ||
            l.contains("readvp8track closed") ||
            (l.contains("readvp8track") && l.contains("err=eof")) ||
            (l.contains("read_err=eof") && l.contains("ack=[0]")) ||
            (l.contains("closed pipe") && !l.contains("peer connection"))
    }

    private fun isPeerClosedLine(line: String): Boolean =
        Regex(
            """peer connection state changed:\s*closed|connection state changed:\s*closed|Setting new connection state:\s*Closed""",
            RegexOption.IGNORE_CASE,
        ).containsMatchIn(line)

    /** STUN/TURN Telemost + сигналинг — не гонять через hev 0.0.0.0/0. */
    private val TELEMOST_BYPASS_HOSTS = listOf(
        "turn.tel.yandex.net",
        "stun.rtc.yandex.net",
        "telemost.yandex.ru",
        "yandex.ru",
        "api.messenger.yandex.net",
        "cloud-api.yandex.net",
        "cloud-api.yandex.ru",
    )

    fun stop(silent: Boolean = false) {
        // Сначала сбрасываем флаги — watchExit не должен слать peer_dead на штатный stop.
        if (!silent) {
            suppressPeerDeadFor(3_000L)
        } else {
            suppressPeerDeadFor(15_000L)
        }
        cancelPeerClosedGrace()
        openStreamFailStreak.set(0)
        lastTunnelActivityMs = 0L
        activeParams = null
        // Prefetch connection-details живут считанные минуты, но после peer closed/recover
        // могут быть уже протухшими для нового процесса и давать media timeout.
        clearPrefetchCaches()
        _tunnelReady.value = false
        _running.value = false
        starting.set(false)
        iceConnected = false
        runCatching { HevSocksTunnel.stopIfLoaded() }
        try {
            tunBridgeProc?.destroy()
        } catch (_: Exception) {
        }
        tunBridgeProc = null
        try {
            olcrtcProc?.destroy()
        } catch (_: Exception) {
        }
        olcrtcProc = null
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
        if (!silent) {
            DebugLog.i("Olcrtc", "session stopped")
            WdttTunnelManager.logUi("olcrtc_stop", "session stopped", 3)
        } else {
            DebugLog.i("Olcrtc", "session stopped (silent)")
        }
    }

    /**
     * Быстрый старт: только валидация на caller-потоке, всё остальное (OkHttp + exec)
     * в фоне — иначе VpnService/ANR (OkHttp до 45с → зависание и вылет).
     */
    fun start(context: Context, params: Params, vpnService: VpnService? = null): String? {
        // Honor/Realme: после code=1 starting/running могли залипнуть — не блокируем reconnect.
        if (!starting.compareAndSet(false, true)) {
            if (_running.value || olcrtcProc != null) {
                DebugLog.w("Olcrtc", "start while busy — force reset")
                stop(silent = true)
            }
            if (!starting.compareAndSet(false, true)) {
                return "olcrtc: already starting"
            }
        }
        _lastError.value = null
        _tunnelReady.value = false
        iceConnected = false
        if (params.cryptoKey.length != 64 || params.room.isBlank()) {
            starting.set(false)
            return "olcrtc: нужны room и crypto_key из /api/vpn/olcrtc-config"
        }
        val olcrtcBin = ensureOlcrtcBinary(context)
            ?: run {
                starting.set(false)
                return "olcrtc: libolcrtc.so не найден в nativeLibraryDir (jniLibs)"
            }

        // Per-session SOCKS login/pass — закрываем 127.0.0.1:8808 от чужих приложений.
        val sessionParams =
            if (params.socksUser.isNotBlank()) {
                params
            } else {
                val creds = generateSocksCreds()
                params.copy(socksUser = creds.first, socksPass = creds.second)
            }

        cancelPeerClosedGrace()
        openStreamFailStreak.set(0)
        activeParams = sessionParams
        val appCtx = context.applicationContext
        _running.value = true
        val engineHint = when (sessionParams.provider.lowercase()) {
            "wbstream" -> "livekit"
            "telemost" -> "goolom"
            else -> "goolom"
        }
        WdttTunnelManager.logUi(
            "olcrtc_start",
            "start ${sessionParams.provider} engine=$engineHint room=${sessionParams.room.take(36)}… socksAuth=on",
            1,
        )

        worker.execute {
            try {
                // Сброс прошлого процесса (без сброса starting — мы уже в старте)
                runCatching { HevSocksTunnel.stopIfLoaded() }
                try {
                    olcrtcProc?.destroy()
                } catch (_: Exception) {
                }
                olcrtcProc = null
                try {
                    tunFd?.close()
                } catch (_: Exception) {
                }
                tunFd = null
                lastFailHint = ""
                iceConnected = false
                _tunnelReady.value = false
                _running.value = true

                val dataDir = File(appCtx.filesDir, "olcrtc-data").apply { mkdirs() }
                val dns = systemDnsHostPort(appCtx)
                val yamlFile = File(appCtx.filesDir, "olcrtc-client.yaml")
                val yaml = renderClientYaml(sessionParams, dns)
                    .replace(Regex("""(?m)^data: data$"""), "data: \"${dataDir.absolutePath}\"")
                yamlFile.writeText(yaml)

                val staticHosts = linkedMapOf<String, String>()
                var telemostConnFile: File? = null
                var wbConnFile: File? = null
                when {
                    sessionParams.provider.equals("telemost", ignoreCase = true) -> {
                        telemostConnFile =
                            prefetchTelemostConnViaOkHttp(appCtx, sessionParams.room, staticHosts)
                    }
                    sessionParams.provider.equals("wbstream", ignoreCase = true) -> {
                        wbConnFile =
                            prefetchWbstreamConnViaOkHttp(appCtx, sessionParams.room, staticHosts)
                    }
                }
                // Часто нужные whitelist-хосты заранее (Java DNS работает, Go — нет)
                resolveInto(staticHosts, "stream.wb.ru", "goloom.strm.yandex.net", "rtc-el-02.wb.ru")

                DebugLog.i(
                    "Olcrtc",
                    "start provider=${sessionParams.provider} bin=$olcrtcBin dns=$dns hosts=${staticHosts.size} socksUser=${sessionParams.socksUser}",
                )
                val libDir = appCtx.applicationInfo.nativeLibraryDir
                if (sessionParams.httpsProxy.isNotBlank()) {
                    WdttTunnelManager.logUi(
                        "olcrtc_proxy",
                        "HTTPS_PROXY=${sessionParams.httpsProxy.take(48)} (legacy)",
                        1,
                    )
                }
                val proc = startOlcrtcProcess(
                    appCtx,
                    olcrtcBin,
                    yamlFile.absolutePath,
                    dataDir,
                    libDir,
                    sessionParams.httpsProxy,
                    telemostConnFile = telemostConnFile,
                    wbConnFile = wbConnFile,
                    staticHosts = staticHosts,
                )
                olcrtcProc = proc
                pipeLogs(proc)
                watchExit(proc)

                if (!waitForSocks(sessionParams.socksHost, sessionParams.socksPort, 90_000, proc)) {
                    val exited = try {
                        proc.exitValue()
                    } catch (_: Exception) {
                        null
                    }
                    val msg = when {
                        exited != null && lastFailHint.isNotBlank() -> lastFailHint
                        exited != null ->
                            "olcrtc вышел code=$exited до SOCKS (бинарь/room/peer)"
                        else ->
                            "olcrtc SOCKS не поднялся на ${sessionParams.socksHost}:${sessionParams.socksPort}"
                    }
                    markStartFailed(msg)
                    WdttTunnelManager.logUi("olcrtc_socks_fail", msg, 99, isError = true)
                    return@execute
                }
                WdttTunnelManager.logUi(
                    "olcrtc_socks",
                    "SOCKS listen ${sessionParams.socksHost}:${sessionParams.socksPort} auth=on",
                    1,
                )
                // Telemost=goolom ICE дольше LiveKit: dial ДО hev, иначе шторм CONNECT
                // от приложений пока peer не готов → ещё медленнее (waiting SOCKS 5s+).
                waitForIceSettled(
                    if (sessionParams.provider.equals("telemost", ignoreCase = true)) 4_000L else 1_200L,
                )
                WdttTunnelManager.logUi("olcrtc_dial_wait", "SOCKS dial… peer/ICE", 1)
                if (!waitForSocksDial(sessionParams, 45_000, proc)) {
                    val msg = if (lastFailHint.isNotBlank()) {
                        lastFailHint
                    } else {
                        "olcrtc SOCKS слушает, но peer не отвечает (dial timeout)"
                    }
                    markStartFailed(msg)
                    WdttTunnelManager.logUi("olcrtc_dial_fail", msg, 99, isError = true)
                    return@execute
                }
                WdttTunnelManager.logUi("olcrtc_dial", "SOCKS dial OK", 1)
                iceConnected = true
                if (vpnService != null) {
                    val tunErr = attachHevTun(appCtx, sessionParams, vpnService)
                    if (tunErr != null) {
                        markStartFailed(tunErr)
                        WdttTunnelManager.logUi("olcrtc_tun_fail", tunErr, 99, isError = true)
                        return@execute
                    }
                } else {
                    WdttTunnelManager.logUi(
                        "olcrtc_tun",
                        "VpnService null — SOCKS-only (трафик приложений без proxy)",
                        3,
                        isError = true,
                    )
                }
                _tunnelReady.value = true
                WdttTunnelManager.logUi("olcrtc_ready", "tunnelReady (SOCKS + hev TUN)", 1)
                // Не держим стартовый трафик YouTube/Chrome за синхронными probe:
                // tunnelReady сразу после SOCKS+TUN, а captive-portal прогрев уводим в фон.
                warmSocksDial(sessionParams, "connectivitycheck.gstatic.com")
                warmSocksDial(sessionParams, "www.gstatic.com")
                warmSocksDial(sessionParams, "www.google.com")
                warmSocksDial(sessionParams, "132-243-234-162.nip.io")
                warmSocksDial(sessionParams, "www.youtube.com")
            } catch (e: Exception) {
                val msg = e.message ?: "olcrtc background start failed"
                markStartFailed(msg)
                WdttTunnelManager.logUi("olcrtc_bg_fail", msg, 99, isError = true)
                DebugLog.e("Olcrtc", "bg start failed", e)
            } finally {
                starting.set(false)
            }
        }
        return null
    }

    /** Ранний fail: сбрасываем running сразу — иначе UI «Подключение…» и recover зависают. */
    private fun markStartFailed(msg: String) {
        _lastError.value = msg
        _tunnelReady.value = false
        _running.value = false
        iceConnected = false
        cancelPeerClosedGrace()
        activeParams = null
        runCatching { HevSocksTunnel.stopIfLoaded() }
        try {
            tunBridgeProc?.destroy()
        } catch (_: Exception) {
        }
        tunBridgeProc = null
        try {
            olcrtcProc?.destroy()
        } catch (_: Exception) {
        }
        olcrtcProc = null
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
        starting.set(false)
    }

    private fun stopKeepStarting() {
        _tunnelReady.value = false
        _running.value = false
        runCatching { HevSocksTunnel.stopIfLoaded() }
        try {
            tunBridgeProc?.destroy()
        } catch (_: Exception) {
        }
        tunBridgeProc = null
        try {
            olcrtcProc?.destroy()
        } catch (_: Exception) {
        }
        olcrtcProc = null
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
    }

    private fun pipeLogs(proc: Process) {
        Thread({
            try {
                BufferedReader(InputStreamReader(proc.inputStream)).use { br ->
                    var line: String?
                    var n = 0
                    while (br.readLine().also { line = it } != null) {
                        val l = line ?: continue
                        n++
                        if (olcrtcProc !== proc) break
                        // pion: [pc]=PeerConnection, [ice]=ICE — не платформа PC
                        if (
                            !isPeerClosedLine(l) &&
                            (
                                l.contains("connection state changed to connected", ignoreCase = true) ||
                                    l.contains("ICE connection state changed to connected", ignoreCase = true) ||
                                    l.contains("Setting new connection state: Connected", ignoreCase = true) ||
                                    Regex(
                                        """peer connection state changed:\s*connected""",
                                        RegexOption.IGNORE_CASE,
                                    ).containsMatchIn(l)
                                )
                        ) {
                            onPeerConnectedAgain()
                        }
                        if (isPeerClosedLine(l)) {
                            DebugLog.i("Olcrtc", l.take(300))
                            WdttTunnelManager.logUi(
                                "olcrtc_pc_closed",
                                l.take(160),
                                priority = 2,
                                isError = false,
                            )
                            // Не kill сразу — goolom сам делает reconnect publisher PC.
                            schedulePeerClosedGrace("peer_closed", 12_000L)
                            continue
                        }
                        if (
                            l.contains("subscriber media timeout", ignoreCase = true) ||
                            l.contains("failed to connect link", ignoreCase = true)
                        ) {
                            schedulePeerClosedGrace("media_timeout", 4_000L)
                        }
                        if (l.contains("OpenStream failed", ignoreCase = true) && _tunnelReady.value) {
                            // Под нагрузкой (speedtest) OpenStream fail нормален — не escalate если трафик идёт.
                            if (hasRecentTunnelTraffic()) {
                                openStreamFailStreak.set(0)
                            } else {
                                val nFail = openStreamFailStreak.incrementAndGet()
                                if (nFail >= 6) {
                                    openStreamFailStreak.set(0)
                                    schedulePeerClosedGrace("openstream_timeout", 3_000L)
                                }
                            }
                        } else if (
                            l.contains("tunnel to ", ignoreCase = true) ||
                            l.contains("Link connected", ignoreCase = true)
                        ) {
                            lastTunnelActivityMs = System.currentTimeMillis()
                            openStreamFailStreak.set(0)
                        }
                        if (Regex(
                                """\[ice\] TRACE|\[sctp\] TRACE|bufferedAmount|service-unavailable|extdisco|disco_1|\[xmpp|Failed to send packet|operation not permitted|Failed to ping without candidate|Failed to listen udp|fe80:|%dummy0|use of closed network connection""",
                                RegexOption.IGNORE_CASE,
                            ).containsMatchIn(l)
                        ) {
                            continue
                        }
                        // Типичный шум Telemost: часть TURN allocate fail при живом peer (host/relay другие).
                        val iceNoise = Regex(
                            """failed to allocate on TURN|failed to get server reflexive|all retransmissions failed|i/o timeout.*stun:|stun:turn\.tel\.yandex|turn\.tel\.yandex\.net""",
                            RegexOption.IGNORE_CASE,
                        ).containsMatchIn(l)
                        val streamNoise = isTransientStreamNoise(l)
                        DebugLog.i("Olcrtc", l.take(300))
                        if (
                            l.contains("failed to send handshake", ignoreCase = true) ||
                            l.contains("WebSocket dial", ignoreCase = true) ||
                            l.contains("xmpp dial", ignoreCase = true)
                        ) {
                            lastFailHint =
                                "WebSocket недоступен (часто DPI на LTE). Wi‑Fi или другой провайдер."
                        } else if (
                            l.contains("netlinkrib", ignoreCase = true) ||
                            l.contains("load interfaces", ignoreCase = true) ||
                            (
                                l.contains("permission denied", ignoreCase = true) &&
                                    l.contains("interface", ignoreCase = true)
                                )
                        ) {
                            lastFailHint =
                                "нет доступа к сетевым интерфейсам (Android/Honor). Переустановите APK с оф. сайта"
                        } else if (
                            l.contains("wait for peer", ignoreCase = true) ||
                            (
                                l.contains("remote not ready", ignoreCase = true) &&
                                    !_tunnelReady.value
                                )
                        ) {
                            lastFailHint =
                                "peer srv не в комнате (проверьте olcrtc@android / не делите data/ с PC)"
                        } else if (
                            l.contains("transport required", ignoreCase = true) ||
                            l.contains("invalid crypto", ignoreCase = true)
                        ) {
                            lastFailHint = "битый olcrtc-config — откройте «Варианты обхода» и обновите"
                        } else if (
                            l.contains("guests cannot create rooms", ignoreCase = true) ||
                            (
                                l.contains("get token failed", ignoreCase = true) &&
                                    l.contains("status 403", ignoreCase = true)
                                )
                        ) {
                            lastFailHint =
                                "WB: гости не могут создать комнату (host без auth.token / мёртвая room) — смените канал"
                        } else if (
                            l.contains("invalid_token", ignoreCase = true) ||
                            (
                                l.contains("join room failed", ignoreCase = true) &&
                                    l.contains("status 401", ignoreCase = true)
                                )
                        ) {
                            lastFailHint = "WB auth.token протух — нужен refresh cookies на сервере"
                        }
                        if (iceNoise) {
                            // В UI один раз как info, не как красная ошибка
                            if (n <= 40) {
                                WdttTunnelManager.logUi(
                                    "olcrtc_ice_noise",
                                    "ICE/TURN warn (часто ок при живом SOCKS): ${l.take(100)}",
                                    priority = 4,
                                    isError = false,
                                )
                            }
                            continue
                        }
                        // Живой туннель + per-stream EOF — не красный «дисконнект» в UI.
                        if (streamNoise && _tunnelReady.value) {
                            if (n <= 8 || n % 25 == 0) {
                                WdttTunnelManager.logUi(
                                    "olcrtc_stream_noise",
                                    "stream warn (туннель жив): ${l.take(120)}",
                                    priority = 4,
                                    isError = false,
                                )
                            }
                            continue
                        }
                        if (streamNoise && !_tunnelReady.value) {
                            // После peer closed — шум closed pipe, не засоряем красным.
                            continue
                        }
                        if (n <= 25 ||
                            l.contains("error", ignoreCase = true) ||
                            l.contains("fail", ignoreCase = true) ||
                            l.contains("SOCKS", ignoreCase = true) ||
                            l.contains("Link connected", ignoreCase = true) ||
                            l.contains("joining", ignoreCase = true) ||
                            l.contains("connection state", ignoreCase = true)
                        ) {
                            val isErr =
                                (l.contains("error", true) || l.contains("fail", true)) &&
                                    !l.contains("connection state", true)
                            WdttTunnelManager.logUi(
                                "olcrtc_log_${l.take(24).hashCode()}",
                                l.take(180),
                                priority = if (isErr) 99 else 3,
                                isError = isErr,
                            )
                        }
                    }
                }
            } catch (_: Exception) {
            }
        }, "olcrtc-log").apply { isDaemon = true }.start()
    }

    /** Ждём ICE connected или таймаут — затем hev TUN. */
    private fun waitForIceSettled(timeoutMs: Long) {
        if (iceConnected) {
            WdttTunnelManager.logUi("olcrtc_ice", "ICE already connected", 2)
            return
        }
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline && !iceConnected) {
            Thread.sleep(200)
        }
        WdttTunnelManager.logUi(
            "olcrtc_ice",
            if (iceConnected) "ICE settled → hev TUN" else "ICE wait timeout → hev TUN (SOCKS уже ок)",
            2,
        )
    }

    private fun watchExit(proc: Process) {
        Thread({
            try {
                val code = proc.waitFor()
                // Важно: после stop() olcrtcProc=null — всё равно это СТАРЫЙ процесс.
                // Раньше при null не выходили → process_exit_early на уже новом старте → recover×N.
                if (olcrtcProc !== proc) {
                    DebugLog.i("Olcrtc", "ignore exit of stale process code=$code")
                    return@Thread
                }
                val wasReady = _tunnelReady.value
                val stillWanted = _running.value
                WdttTunnelManager.logUi(
                    "olcrtc_exit",
                    "olcrtc process exit code=$code",
                    if (stillWanted) 2 else 3,
                    isError = stillWanted && code != 0,
                )
                when {
                    // Только после ready: early exit во время старта → markStartFailed (без залипания).
                    stillWanted && wasReady -> notifyPeerDead("process_exit:$code")
                    stillWanted && !wasReady -> {
                        val msg = when {
                            lastFailHint.isNotBlank() -> lastFailHint
                            else -> "olcrtc вышел code=$code"
                        }
                        markStartFailed(msg)
                        WdttTunnelManager.logUi("olcrtc_exit_early", msg, 99, isError = true)
                    }
                }
            } catch (_: Exception) {
            }
        }, "olcrtc-exit").apply { isDaemon = true }.start()
    }

    /** Как WDTT: debug — меню DNS; иначе Яндекс. */
    private fun resolveOlcrtcDnsServers(context: Context): List<String> {
        val raw = if (BuildConfig.DEBUG) {
            val id = SilentPrefs.open(context)
                .getString(SilentRepository.PREF_DNS_PRESET, DnsPreset.DEFAULT.id)
            DnsPreset.fromId(id).servers
        } else {
            DnsPreset.DEFAULT.servers
        }
        return raw.split(",")
            .map { it.trim() }
            .filter { it.isNotBlank() && !it.contains(':') }
            .ifEmpty { listOf("77.88.8.8", "77.88.8.1") }
    }

    /**
     * TUN → SOCKS через hev.
     *
     * olcrtc SOCKS = только TCP CONNECT: UDP:53 в TUN мёртв.
     * Поэтому mapdns/fake-ip (как раньше / как PC): VPN DNS = 198.18.0.2,
     * приложения получают fake IP → SOCKS CONNECT по домену → резолв на peer.
     *
     * Меню DnsPreset для olcrtc намеренно не ставим в Builder: на LTE
     * UDP к 1.1.1.1/8.8.8.8 вне TUN оператор часто режет → «интернет пропал».
     * (WDTT по-прежнему берёт пресет — DNS идёт через WG на VPS.)
     */
    private fun attachHevTun(context: Context, params: Params, vpnService: VpnService): String? {
        if (!HevSocksTunnel.ensureLoaded()) {
            return "libhev-socks5-tunnel.so не загружен"
        }
        // Повторный старт (смена WB→Telemost) без stop → TProxyStartService failed.
        runCatching { HevSocksTunnel.stopIfLoaded() }
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
        Thread.sleep(200)
        val menuDns = resolveOlcrtcDnsServers(context)
        val conf = File(context.filesDir, "hev-olcrtc.yml")
        // 198.18.0.0/15 — как sing-box fake-ip на PC; mapdns отвечает на 198.18.0.2:53.
        val hevYaml = buildString {
            appendLine("tunnel:")
            // 1400 ≈ KCP MTU olcrtc; 1280 резал TCP MSS без нужды.
            appendLine("  mtu: 1400")
            appendLine("  ipv4: 198.18.0.1")
            appendLine("socks5:")
            appendLine("  port: ${params.socksPort}")
            appendLine("  address: ${params.socksHost}")
            appendLine("  udp: 'udp'")
            if (params.socksUser.isNotBlank()) {
                val u = params.socksUser.replace("'", "''")
                val p = params.socksPass.replace("'", "''")
                appendLine("  username: '$u'")
                appendLine("  password: '$p'")
            }
            appendLine("mapdns:")
            appendLine("  address: 198.18.0.2")
            appendLine("  port: 53")
            appendLine("  network: 198.18.0.0")
            appendLine("  netmask: 255.254.0.0")
            appendLine("  cache-size: 10000")
            appendLine("misc:")
            appendLine("  log-level: warn")
            appendLine("  connect-timeout: 8000")
            appendLine("  tcp-read-write-timeout: 300000")
            appendLine("  udp-read-write-timeout: 800")
        }
        conf.writeText(hevYaml)
        return try {
            val builder = vpnService.Builder()
                .setSession("Silent olcrtc")
                .setMtu(1400)
                .addAddress("198.18.0.1", 30)
                .addRoute("0.0.0.0", 0)
                // Только mapdns — не 8.8.8.8/1.1.1.1 (на LTE часто мёртв вне TUN).
                .addDnsServer("198.18.0.2")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                runCatching { builder.allowFamily(OsConstants.AF_INET) }
                WdttTunnelManager.logUi(
                    "olcrtc_tun_v4",
                    "IPv4-only + mapdns fake-ip (меню DNS=${menuDns.joinToString(",")} — для olcrtc не в LTE)",
                    2,
                )
            }
            // API 33+: ICE/STUN Telemost/WB напрямую; системный DNS — fallback для приложений,
            // которые игнорируют VPN DNS (иначе снова UDP:53 в TUN → сайты мертвы).
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val excludeHosts = linkedSetOf<String>()
                excludeHosts.addAll(systemDnsIpv4Hosts(context))
                if (params.provider.equals("telemost", ignoreCase = true) ||
                    params.provider.equals("wbstream", ignoreCase = true)
                ) {
                    excludeHosts.addAll(TELEMOST_BYPASS_HOSTS)
                    excludeHosts.add("stream.wb.ru")
                    excludeHosts.add("stream-meetup.wildberries.ru")
                }
                var excluded = 0
                for (host in excludeHosts) {
                    excluded += excludeHostRoutes(builder, host)
                }
                WdttTunnelManager.logUi(
                    "olcrtc_tun_excl",
                    "excludeRoute hosts=${excludeHosts.size} ips≈$excluded mapdns=198.18.0.2",
                    2,
                )
            }
            runCatching { builder.addDisallowedApplication(context.packageName) }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                runCatching { builder.setMetered(false) }
            }
            // До establish: после TUN activeNetwork уже сам VPN.
            val underlyingNet = runCatching {
                context.getSystemService(ConnectivityManager::class.java)?.activeNetwork
            }.getOrNull()
            val pfd = builder.establish()
                ?: return "VpnService.Builder.establish() вернул null"
            tunFd = pfd
            // Чтобы Chrome/система не считали VPN «оторванным» от LTE/Wi‑Fi.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP_MR1 && underlyingNet != null) {
                runCatching { vpnService.setUnderlyingNetworks(arrayOf(underlyingNet)) }
            }
            val ok = HevSocksTunnel.TProxyStartService(conf.absolutePath, pfd.fd)
            if (!ok) {
                runCatching { pfd.close() }
                tunFd = null
                return "hev TProxyStartService failed"
            }
            WdttTunnelManager.logUi(
                "olcrtc_tun",
                "hev TUN ok fd=${pfd.fd} mapdns=fake-ip (сайты≠Telegram-IP)",
                1,
            )
            null
        } catch (e: Exception) {
            "hev TUN: ${e.message}"
        }
    }

    /** IPv4 DNS оператора/Wi‑Fi — для excludeRoute (API 33+). */
    private fun systemDnsIpv4Hosts(context: Context): List<String> {
        return try {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            val servers = cm?.getLinkProperties(cm.activeNetwork)?.dnsServers.orEmpty()
            servers.mapNotNull { it.hostAddress?.takeIf { ip -> ip.isNotBlank() && !ip.contains(':') } }
        } catch (_: Exception) {
            emptyList()
        }
    }

    /** Resolve host → excludeRoute /32 для каждого A-записи (API 33+). */
    private fun excludeHostRoutes(builder: VpnService.Builder, host: String): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return 0
        var n = 0
        // Уже IP — не резолвить
        val parsed = runCatching { InetAddress.getByName(host) }.getOrNull()
        if (parsed != null && parsed.hostAddress == host && parsed.address?.size == 4) {
            runCatching {
                builder.excludeRoute(IpPrefix(parsed, 32))
                return 1
            }
        }
        val addrs = runCatching { InetAddress.getAllByName(host) }.getOrNull() ?: return 0
        for (addr in addrs) {
            if (addr.address?.size != 4) continue
            runCatching {
                builder.excludeRoute(IpPrefix(addr, 32))
                n++
            }
        }
        return n
    }

    private fun generateSocksCreds(): Pair<String, String> {
        val rnd = SecureRandom()
        val userBytes = ByteArray(6)
        val passBytes = ByteArray(18)
        rnd.nextBytes(userBytes)
        rnd.nextBytes(passBytes)
        val user = "s" + userBytes.joinToString("") { "%02x".format(it) }
        val pass =
            Base64.encodeToString(passBytes, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        return user to pass
    }

    /** SOCKS5 CONNECT по домену — peer + DNS через туннель (как на PC). */
    private fun waitForSocksDial(params: Params, timeoutMs: Long, proc: Process? = null): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (proc != null && !isProcessAlive(proc)) return false
            if (!_running.value) return false
            if (socksDialOnce(params, "www.gstatic.com", soTimeoutMs = 4000)) {
                return true
            }
            Thread.sleep(250)
        }
        return false
    }

    private fun warmSocksDial(params: Params, domain: String) {
        Thread({
            repeat(3) {
                if (socksDialOnce(params, domain, soTimeoutMs = 10000)) {
                    WdttTunnelManager.logUi("olcrtc_warm", "warm TCP $domain OK", 2)
                    return@Thread
                }
                Thread.sleep(400)
            }
            WdttTunnelManager.logUi("olcrtc_warm", "warm TCP $domain fail", 3)
        }, "olcrtc-warm").apply { isDaemon = true }.start()
    }

    /** SOCKS5 CONNECT + optional RFC1929 user/pass. */
    private fun socksDialOnce(params: Params, domain: String, soTimeoutMs: Int): Boolean {
        val host = params.socksHost
        val port = params.socksPort
        val domainBytes = domain.toByteArray(Charsets.US_ASCII)
        if (domainBytes.size > 255) return false
        val needAuth = params.socksUser.isNotBlank()
        return try {
            Socket().use { s ->
                s.soTimeout = soTimeoutMs
                s.connect(InetSocketAddress(host, port), 800)
                val out = s.getOutputStream()
                val inp = s.getInputStream()
                out.write(
                    if (needAuth) byteArrayOf(0x05, 0x01, 0x02) else byteArrayOf(0x05, 0x01, 0x00),
                )
                val greet = ByteArray(2)
                if (inp.read(greet) < 2 || greet[0] != 0x05.toByte()) return false
                if (needAuth) {
                    if (greet[1] != 0x02.toByte()) return false
                    val ub = params.socksUser.toByteArray(Charsets.UTF_8)
                    val pb = params.socksPass.toByteArray(Charsets.UTF_8)
                    if (ub.size > 255 || pb.size > 255) return false
                    val auth = ByteArray(3 + ub.size + pb.size)
                    auth[0] = 0x01
                    auth[1] = ub.size.toByte()
                    System.arraycopy(ub, 0, auth, 2, ub.size)
                    auth[2 + ub.size] = pb.size.toByte()
                    System.arraycopy(pb, 0, auth, 3 + ub.size, pb.size)
                    out.write(auth)
                    val authResp = ByteArray(2)
                    if (inp.read(authResp) < 2 ||
                        authResp[0] != 0x01.toByte() ||
                        authResp[1] != 0x00.toByte()
                    ) {
                        return false
                    }
                } else if (greet[1] != 0x00.toByte()) {
                    return false
                }
                val req = ByteArray(5 + domainBytes.size + 2)
                req[0] = 0x05
                req[1] = 0x01
                req[3] = 0x03
                req[4] = domainBytes.size.toByte()
                System.arraycopy(domainBytes, 0, req, 5, domainBytes.size)
                val p = 5 + domainBytes.size
                req[p] = 0x01
                req[p + 1] = 0xBB.toByte() // 443
                out.write(req)
                val resp = ByteArray(2)
                inp.read(resp) >= 2 && resp[1] == 0x00.toByte()
            }
        } catch (_: Exception) {
            false
        }
    }

    fun startFromConfigJson(context: Context, json: String, vpnService: VpnService? = null): String? {
        cachedConfigJson = json
        val obj = JSONObject(json)
        val svc = vpnService ?: (context as? VpnService)
        return start(
            context,
            Params(
                provider = obj.optString("olcrtc_provider", "telemost"),
                room = obj.optString("olcrtc_room"),
                cryptoKey = obj.optString("olcrtc_crypto_key"),
                transport = obj.optString("olcrtc_transport", "datachannel"),
                socksHost = obj.optString("olcrtc_socks_host", "127.0.0.1"),
                socksPort = obj.optInt("olcrtc_socks_port", 8808),
                isBootstrap = obj.optBoolean("is_bootstrap", false),
                httpsProxy = obj.optString("olcrtc_https_proxy", ""),
                authToken = obj.optString("olcrtc_auth_token", ""),
            ),
            vpnService = svc,
        )
    }

    /**
     * Android 10+: нельзя exec из writable dirs (filesDir/codeCache → error=13).
     * Только nativeLibraryDir/libolcrtc.so (как libclient). codeCache — лишь TV-fallback.
     */
    private fun ensureOlcrtcBinary(ctx: Context): String? {
        val abi = android.os.Build.SUPPORTED_ABIS.firstOrNull().orEmpty()
        val so = File(ctx.applicationInfo.nativeLibraryDir, "libolcrtc.so")
        if (!so.exists() || so.length() == 0L) {
            DebugLog.e("Olcrtc", "libolcrtc.so missing in ${ctx.applicationInfo.nativeLibraryDir}")
            WdttTunnelManager.logUi(
                "olcrtc_bin_missing",
                "libolcrtc.so missing nativeLibraryDir abi=$abi",
                99,
                isError = true,
            )
            return null
        }
        WdttTunnelManager.logUi(
            "olcrtc_bin",
            "binary ok size=${so.length()} abi=$abi path=native/${so.name}",
            1,
        )
        return so.absolutePath
    }

    private fun whitelistHttpClient(context: Context): OkHttpClient {
        val builder = OkHttpClient.Builder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(12, TimeUnit.SECONDS)
            .callTimeout(20, TimeUnit.SECONDS)
            .followRedirects(true)
        runCatching {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            // Если основной VK-VPN уже поднят и app excluded, Telemost/WB signaling на LTE
            // должен идти через VPN-сеть, а не напрямую в заблокированный интернет.
            val net = VpnNetworkHelper.getSilentVpnNetwork(context) ?: cm?.activeNetwork
            if (net != null) builder.socketFactory(net.socketFactory)
        }
        return builder.build()
    }

    private fun systemDnsHostPort(context: Context): String {
        return try {
            val cm = context.getSystemService(ConnectivityManager::class.java)
            val dns = cm?.getLinkProperties(cm.activeNetwork)?.dnsServers?.firstOrNull()
            val host = dns?.hostAddress?.takeIf { it.isNotBlank() && !it.contains(':') }
            if (host != null) "$host:53" else "1.1.1.1:53"
        } catch (_: Exception) {
            "1.1.1.1:53"
        }
    }

    private fun resolveInto(out: MutableMap<String, String>, vararg hosts: String) {
        for (h in hosts) {
            if (h.isBlank() || out.containsKey(h.lowercase())) continue
            val ip = runCatching {
                InetAddress.getAllByName(h).firstOrNull { it.hostAddress?.contains(':') != true }?.hostAddress
            }.getOrNull()
            if (!ip.isNullOrBlank()) {
                out[h.lowercase()] = ip
            }
        }
    }

    private fun hostFromUrl(url: String): String? = try {
        java.net.URI(url).host?.takeIf { it.isNotBlank() }
    } catch (_: Exception) {
        null
    }

    /** Telemost: OkHttp → cloud-api (whitelist). */
    private fun prefetchTelemostConnViaOkHttp(
        context: Context,
        room: String,
        staticHosts: MutableMap<String, String>,
    ): File? {
        val cached = telemostPrefetchCache
        if (
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = cached?.room,
                    requestRoom = room,
                    untilMs = cached?.untilMs ?: 0L,
                    nowMs = System.currentTimeMillis(),
                    fileExists = cached?.file?.isFile == true,
                ),
            )
        ) {
            WdttTunnelManager.logUi("olcrtc_tm_auth", "Yandex auth cache hit", 1)
            runCatching {
                val media = JSONObject(cached!!.file.readText())
                    .optJSONObject("client_configuration")
                    ?.optString("media_server_url")
                    .orEmpty()
                hostFromUrl(media)?.let { resolveInto(staticHosts, it) }
            }
            resolveInto(staticHosts, "cloud-api.yandex.ru", "telemost.yandex.ru", "goloom.strm.yandex.net")
            return cached!!.file
        }
        return try {
            val roomUrl =
                if (room.startsWith("https://")) room
                else "https://telemost.yandex.ru/j/$room"
            val enc = URLEncoder.encode(roomUrl, Charsets.UTF_8.name())
            val url =
                "https://cloud-api.yandex.ru/telemost_front/v2/telemost/conferences/$enc/connection" +
                    "?next_gen_media_platform_allowed=true" +
                    "&display_name=silent-android" +
                    "&waiting_room_supported=true"
            resolveInto(staticHosts, "cloud-api.yandex.ru", "telemost.yandex.ru")
            val req = Request.Builder()
                .url(url)
                .get()
                .header(
                    "User-Agent",
                    "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36",
                )
                .header("Accept", "*/*")
                .header("Content-Type", "application/json")
                .header("Client-Instance-Id", UUID.randomUUID().toString())
                .header("X-Telemost-Client-Version", "187.1.0")
                .header("Idempotency-Key", UUID.randomUUID().toString())
                .header("Origin", "https://telemost.yandex.ru")
                .header("Referer", "https://telemost.yandex.ru/")
                .build()
            whitelistHttpClient(context).newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    WdttTunnelManager.logUi(
                        "olcrtc_tm_auth",
                        "Yandex OkHttp ${resp.code}: ${body.take(80)}",
                        99,
                        isError = true,
                    )
                    return null
                }
                val obj = JSONObject(body)
                val media = obj.optJSONObject("client_configuration")?.optString("media_server_url").orEmpty()
                if (obj.optString("room_id").isBlank() ||
                    obj.optString("peer_id").isBlank() ||
                    media.isBlank()
                ) {
                    WdttTunnelManager.logUi(
                        "olcrtc_tm_auth",
                        "Yandex OkHttp: нет room_id/peer_id/media",
                        99,
                        isError = true,
                    )
                    return null
                }
                hostFromUrl(media)?.let { resolveInto(staticHosts, it) }
                val f = File(context.filesDir, "telemost-conn.json")
                f.writeText(body)
                telemostPrefetchCache = PrefetchCache(
                    room,
                    f,
                    System.currentTimeMillis() + OlcrtcRecoveryPolicy.PREFETCH_TTL_MS,
                )
                WdttTunnelManager.logUi("olcrtc_tm_auth", "Yandex auth OkHttp OK (whitelist)", 1)
                f
            }
        } catch (e: Exception) {
            WdttTunnelManager.logUi("olcrtc_tm_auth", "Yandex OkHttp fail: ${e.message?.take(100)}", 3)
            DebugLog.e("Olcrtc", "telemost OkHttp prefetch failed", e)
            null
        }
    }

    /** WB: guest-register → join → connection-details через OkHttp (whitelist). */
    private fun prefetchWbstreamConnViaOkHttp(
        context: Context,
        room: String,
        staticHosts: MutableMap<String, String>,
    ): File? {
        val cached = wbPrefetchCache
        if (
            OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                OlcrtcRecoveryPolicy.PrefetchReuseInput(
                    cachedRoom = cached?.room,
                    requestRoom = room,
                    untilMs = cached?.untilMs ?: 0L,
                    nowMs = System.currentTimeMillis(),
                    fileExists = cached?.file?.isFile == true,
                ),
            )
        ) {
            WdttTunnelManager.logUi("olcrtc_wb_auth", "WB auth cache hit", 1)
            runCatching {
                val url = JSONObject(cached!!.file.readText()).optString("url")
                hostFromUrl(url)?.let { resolveInto(staticHosts, it) }
            }
            resolveInto(staticHosts, "stream.wb.ru", "rtc-el-02.wb.ru")
            return cached!!.file
        }
        return try {
            val roomId = room.trim().removePrefix("https://stream.wb.ru/room/").trim('/')
            if (roomId.isBlank()) return null
            resolveInto(staticHosts, "stream.wb.ru")
            val client = whitelistHttpClient(context)
            val ua = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"

            val regBody = JSONObject()
                .put("displayName", "silent-android")
                .put(
                    "device",
                    JSONObject()
                        .put("deviceName", "Android")
                        .put("deviceType", "PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP"),
                )
                .toString()
            val jsonMedia = "application/json".toMediaType()
            val regReq = Request.Builder()
                .url("https://stream.wb.ru/auth/api/v1/auth/user/guest-register")
                .post(regBody.toRequestBody(jsonMedia))
                .header("User-Agent", ua)
                .header("Content-Type", "application/json")
                .build()
            val accessToken = client.newCall(regReq).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    WdttTunnelManager.logUi(
                        "olcrtc_wb_auth",
                        "WB guest ${resp.code}: ${body.take(80)}",
                        99,
                        isError = true,
                    )
                    return null
                }
                JSONObject(body).optString("accessToken")
            }
            if (accessToken.isBlank()) {
                WdttTunnelManager.logUi("olcrtc_wb_auth", "WB guest: нет accessToken", 99, isError = true)
                return null
            }

            val joinReq = Request.Builder()
                .url("https://stream.wb.ru/api-room/api/v1/room/$roomId/join")
                .post("{}".toRequestBody(jsonMedia))
                .header("User-Agent", ua)
                .header("Authorization", "Bearer $accessToken")
                .header("Content-Type", "application/json")
                .build()
            client.newCall(joinReq).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        val body = resp.body?.string().orEmpty()
                        WdttTunnelManager.logUi(
                            "olcrtc_wb_auth",
                            "WB join ${resp.code}: ${body.take(80)}",
                            99,
                            isError = true,
                        )
                        if (body.contains("guests cannot create rooms", ignoreCase = true)) {
                            lastFailHint =
                                "WB: гости не могут создать комнату (host без auth.token / мёртвая room) — смените канал"
                        }
                        return null
                    }
            }

            val tokUrl =
                "https://stream.wb.ru/api-room-manager/v2/room/$roomId/connection-details" +
                    "?deviceType=PARTICIPANT_DEVICE_TYPE_WEB_DESKTOP&displayName=silent-android"
            val tokReq = Request.Builder()
                .url(tokUrl)
                .get()
                .header("User-Agent", ua)
                .header("Authorization", "Bearer $accessToken")
                .build()
            val (serverUrl, roomToken) = client.newCall(tokReq).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    WdttTunnelManager.logUi(
                        "olcrtc_wb_auth",
                        "WB token ${resp.code}: ${body.take(80)}",
                        99,
                        isError = true,
                    )
                    if (body.contains("guests cannot create rooms", ignoreCase = true)) {
                        lastFailHint =
                            "WB: гости не могут создать комнату (host без auth.token / мёртвая room) — смените канал"
                    }
                    return null
                }
                val o = JSONObject(body)
                o.optString("serverUrl").ifBlank { "wss://rtc-el-02.wb.ru" } to o.optString("roomToken")
            }
            if (roomToken.isBlank()) {
                WdttTunnelManager.logUi("olcrtc_wb_auth", "WB token: пустой roomToken", 99, isError = true)
                return null
            }
            hostFromUrl(serverUrl)?.let { resolveInto(staticHosts, it) }
            val out = JSONObject()
                .put("url", serverUrl)
                .put("token", roomToken)
                .put("roomID", roomId)
                .toString()
            val f = File(context.filesDir, "wbstream-conn.json")
            f.writeText(out)
            wbPrefetchCache = PrefetchCache(
                room,
                f,
                System.currentTimeMillis() + OlcrtcRecoveryPolicy.PREFETCH_TTL_MS,
            )
            WdttTunnelManager.logUi("olcrtc_wb_auth", "WB auth OkHttp OK (whitelist)", 1)
            f
        } catch (e: Exception) {
            WdttTunnelManager.logUi("olcrtc_wb_auth", "WB OkHttp fail: ${e.message?.take(100)}", 3)
            DebugLog.e("Olcrtc", "wbstream OkHttp prefetch failed", e)
            null
        }
    }

    private fun startOlcrtcProcess(
        context: Context,
        primaryBin: String,
        yamlPath: String,
        dataDir: File,
        libDir: String,
        httpsProxy: String = "",
        telemostConnFile: File? = null,
        wbConnFile: File? = null,
        staticHosts: Map<String, String> = emptyMap(),
    ): Process {
        val cmd = listOf(primaryBin, yamlPath)
        try {
            WdttTunnelManager.logUi("olcrtc_exec", "exec native/${File(primaryBin).name}", 2)
            return buildOlcrtcProcess(
                cmd, dataDir, libDir, httpsProxy, telemostConnFile, wbConnFile, staticHosts,
            ).start()
        } catch (e: java.io.IOException) {
            if (!com.silent.vpn.util.DevicePlatform.isTv(context)) {
                WdttTunnelManager.logUi(
                    "olcrtc_exec_fail",
                    "exec native failed: ${e.message}",
                    99,
                    isError = true,
                )
                throw e
            }
            val abi = android.os.Build.SUPPORTED_ABIS.firstOrNull().orEmpty()
            val src = File(context.applicationInfo.nativeLibraryDir, "libolcrtc.so")
            val dest = File(context.codeCacheDir, "olcrtc-tv-$abi.so")
            src.copyTo(dest, overwrite = true)
            dest.setReadable(true, false)
            dest.setWritable(true, false)
            dest.setExecutable(true, false)
            WdttTunnelManager.logUi(
                "olcrtc_exec_fb",
                "TV fallback codeCache after: ${e.message}",
                3,
            )
            return buildOlcrtcProcess(
                listOf(dest.absolutePath, yamlPath),
                dataDir,
                libDir,
                httpsProxy,
                telemostConnFile,
                wbConnFile,
                staticHosts,
            ).start()
        }
    }

    private fun buildOlcrtcProcess(
        cmd: List<String>,
        dataDir: File,
        libDir: String,
        httpsProxy: String = "",
        telemostConnFile: File? = null,
        wbConnFile: File? = null,
        staticHosts: Map<String, String> = emptyMap(),
    ): ProcessBuilder =
        ProcessBuilder(cmd).apply {
            directory(dataDir)
            redirectErrorStream(true)
            environment()["LD_LIBRARY_PATH"] = libDir
            telemostConnFile?.takeIf { it.isFile }?.let {
                environment()["OLCRTC_TELEMOST_CONN_FILE"] = it.absolutePath
            }
            wbConnFile?.takeIf { it.isFile }?.let {
                environment()["OLCRTC_WBSTREAM_CONN_FILE"] = it.absolutePath
            }
            if (staticHosts.isNotEmpty()) {
                environment()["OLCRTC_STATIC_HOSTS"] =
                    staticHosts.entries.joinToString(";") { "${it.key}=${it.value}" }
                WdttTunnelManager.logUi(
                    "olcrtc_dns",
                    "STATIC_HOSTS=${staticHosts.size} (Java DNS → Go dial)",
                    2,
                )
            }
            val proxy = httpsProxy.trim()
            if (proxy.isNotEmpty()) {
                environment()["HTTPS_PROXY"] = proxy
                environment()["HTTP_PROXY"] = proxy
                environment()["https_proxy"] = proxy
                environment()["http_proxy"] = proxy
                environment()["ALL_PROXY"] = proxy
                environment()["all_proxy"] = proxy
            }
        }

    private fun findBinary(ctx: Context, names: List<String>): String? {
        val dirs = listOf(
            File(ctx.applicationInfo.nativeLibraryDir),
            ctx.codeCacheDir,
        )
        for (dir in dirs) {
            for (name in names) {
                val f = File(dir, name)
                if (f.exists() && f.canExecute()) return f.absolutePath
                if (f.exists()) {
                    f.setExecutable(true)
                    if (f.canExecute()) return f.absolutePath
                }
            }
        }
        return null
    }

    private fun isProcessAlive(proc: Process): Boolean =
        try {
            proc.exitValue()
            false
        } catch (_: IllegalThreadStateException) {
            true
        } catch (_: Exception) {
            false
        }

    private fun waitForSocks(host: String, port: Int, timeoutMs: Long, proc: Process? = null): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (proc != null && !isProcessAlive(proc)) return false
            if (!_running.value) return false
            try {
                Socket().use { s ->
                    s.connect(InetSocketAddress(host, port), 800)
                    return true
                }
            } catch (_: Exception) {
                Thread.sleep(300)
            }
        }
        return false
    }

    private fun renderClientYaml(p: Params, dns: String = "1.1.1.1:53"): String {
        // Не использовать trimIndent + вставку token с другим отступом:
        // min-indent ломает YAML → net.transport пустой → «transport required».
        val transport = p.transport.ifBlank {
            when (p.provider.lowercase()) {
                "wbstream", "telemost" -> "vp8channel"
                else -> "datachannel"
            }
        }
        val lines = mutableListOf(
            "mode: cnc",
            "auth:",
            "  provider: ${p.provider}",
        )
        if (p.authToken.isNotBlank()) {
            val esc = p.authToken.replace("\\", "\\\\").replace("\"", "\\\"")
            lines += "  token: \"$esc\""
        }
        lines += listOf(
            "room:",
            "  id: \"${p.room}\"",
            "crypto:",
            "  key: \"${p.cryptoKey}\"",
            "net:",
            "  transport: $transport",
            "  dns: \"$dns\"",
            "socks:",
            "  host: \"${p.socksHost}\"",
            "  port: ${p.socksPort}",
        )
        if (p.socksUser.isNotBlank()) {
            val u = p.socksUser.replace("\\", "\\\\").replace("\"", "\\\"")
            val pw = p.socksPass.replace("\\", "\\\\").replace("\"", "\\\"")
            lines += "  user: \"$u\""
            lines += "  pass: \"$pw\""
        }
        // Community URI vp8-fps=60 — выше emission rate к потолку SFU.
        if (transport == "vp8channel") {
            lines += listOf("vp8:", "  fps: 60", "  batch_size: 64")
        }
        lines += listOf("data: data", "")
        return lines.joinToString("\n")
    }
}
