package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.IpPrefix
import android.net.NetworkCapabilities
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import android.system.OsConstants
import com.silent.vpn.BuildConfig
import com.silent.vpn.data.DnsSettings
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
        /** olcrtc 2.0: libolcrtc2.so + env OLCRTC2_* (без YAML). */
        val olcrtc2: Boolean = true,
    )

    /** Локальный SOCKS для HTTP (app disallow → LTE HB через peer, не underlying nip.io). */
    data class SocksEndpoint(
        val host: String,
        val port: Int,
        val user: String,
        val pass: String,
    )

    /** false → DNS=real через несущую (откат одной строкой). */
    private const val OLCRTC2_MAPDNS = true
    private const val MAPDNS_ADDRESS = "198.18.0.2"
    /** Пул fake IP. Не 100.64.0.0/10 (дефолт hev) — это CGNAT LTE, ломает ICE. */
    private const val MAPDNS_NETWORK = "198.19.0.0"
    private const val MAPDNS_NETMASK = "255.255.0.0"

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
    /** Старый worker после выкл. не должен hardReset'ить новый connect. */
    private val startEpoch = AtomicInteger(0)

    fun isStarting(): Boolean = starting.get()
    fun currentEpoch(): Int = startEpoch.get()

    /** onDestroy/STOP предыдущего цикла не должен убивать уже стартовавший connect. */
    fun shouldIgnoreStaleVpnTeardown(bindEpoch: Int): Boolean {
        if (starting.get()) return true
        val cur = startEpoch.get()
        return bindEpoch != 0 && bindEpoch < cur
    }
    @Volatile private var lastFailHint: String = ""
    /** ICE PeerConnection connected — можно поднимать hev full-tunnel. */
    @Volatile private var iceConnected = false
    /** vp8 peer latched / session opened — room жива, SOCKS может открыться позже 8с. */
    @Volatile private var peerLatched = false
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
    private val streamDeadStreak = AtomicInteger(0)
    /** Heartbeat/API CONNECT через SOCKS при готовом туннеле. */
    private val socksApiFailStreak = AtomicInteger(0)
    /** Последний успешный SOCKS tunnel (speedtest/Intermeter грузят peer — не SOCKS_DEAD). */
    @Volatile private var lastTunnelActivityMs = 0L
    /**
     * missed_pong / remote-not-ready: peer уже мёртв, а «recent traffic» / fake SOCKS
     * держат UI зелёным — не доверяем им до реального dial.
     */
    @Volatile private var peerLivenessSuspect = false
    private var healthWatchFuture: ScheduledFuture<*>? = null
    private val healthFailStreak = AtomicInteger(0)
    private val scheduler = Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "olcrtc-grace").apply { isDaemon = true }
    }
    /** Кэш OkHttp auth (room → file + expiry), чтобы reconnect был ближе к VK. */
    private data class PrefetchCache(val room: String, val file: File, val untilMs: Long)
    @Volatile private var telemostPrefetchCache: PrefetchCache? = null
    @Volatile private var wbPrefetchCache: PrefetchCache? = null
    /** filesDir для wipe CONN_FILE при early fail (без Context в markStartFailed). */
    @Volatile private var filesDirRef: File? = null
    /** IPv4 из STATIC_HOSTS — excludeRoute без повторного DNS (иначе +1–3с до TUN). */
    @Volatile private var lastStaticHostIps: Map<String, String> = emptyMap()
    private val worker = Executors.newSingleThreadExecutor { r ->
        Thread(r, "olcrtc-start").apply { isDaemon = true }
    }

    fun lastConfigJson(): String? = cachedConfigJson

    fun activeSocksEndpoint(): SocksEndpoint? {
        val p = activeParams ?: return null
        if (!_tunnelReady.value || !_running.value) return null
        if (p.socksUser.isBlank() || p.socksPass.isBlank()) return null
        return SocksEndpoint(
            host = p.socksHost.ifBlank { "127.0.0.1" },
            port = p.socksPort,
            user = p.socksUser,
            pass = p.socksPass,
        )
    }

    fun setSessionDeadHandler(handler: ((String) -> Unit)?) {
        sessionDeadHandler = handler
    }

    fun suppressPeerDeadFor(ms: Long) {
        suppressPeerDeadUntilMs = System.currentTimeMillis() + ms.coerceAtLeast(0L)
    }

    /** Были ли «tunnel to …» недавно — peer жив даже если gstatic probe таймаутится. */
    fun hasRecentTunnelTraffic(nowMs: Long = System.currentTimeMillis()): Boolean =
        OlcrtcRecoveryPolicy.hasRecentTunnelTraffic(lastTunnelActivityMs, nowMs)

    /** missed_pong / stream_dead / socks API fail — не доверять «recent traffic». */
    fun isPeerLivenessSuspect(): Boolean = peerLivenessSuspect

    /** Heartbeat/API через SOCKS прошёл — data plane жив. */
    fun noteSocksPathOk() {
        socksApiFailStreak.set(0)
        lastTunnelActivityMs = System.currentTimeMillis()
    }

    /**
     * SOCKS CONNECT/POST к API упал при tunnelReady.
     * Underlying Wi‑Fi HB не лечит data plane — после N fail → suspect → reassign.
     */
    fun noteSocksPathFail(detail: String = "socks_api") {
        if (!_tunnelReady.value || !_running.value) return
        val n = socksApiFailStreak.incrementAndGet()
        DebugLog.w("Olcrtc", "socks path fail n=$n ($detail)")
        if (n < OlcrtcRecoveryPolicy.SOCKS_API_FAIL_SUSPECT_STREAK) return
        socksApiFailStreak.set(0)
        if (OlcrtcRecoveryPolicy.shouldForceSocksDialOnLivenessSuspect()) {
            markPeerLivenessSuspect("socks_api_fail", 4_000L)
        }
    }

    /** true если SOCKS dial к gstatic проходит (peer жив). */
    fun probeSocksHealthy(forceDial: Boolean = false): Boolean {
        val p = activeParams ?: return false
        if (!_running.value) return false
        // При живом speedtest/Intermeter gstatic часто не успевает за 3.5с — не врём «мёртв».
        // Но missed_pong / stream_dead — только реальный dial.
        if (!forceDial && !peerLivenessSuspect && hasRecentTunnelTraffic()) return true
        return socksDialOnce(p, "www.gstatic.com", soTimeoutMs = 3_500)
    }

    private fun markPeerLivenessSuspect(reason: String, graceMs: Long = 8_000L) {
        peerLivenessSuspect = true
        WdttTunnelManager.logUi(
            "olcrtc_liveness",
            "peer suspect ($reason) — без SOCKS-пробы (не рвём видео)",
            2,
        )
        if (!OlcrtcRecoveryPolicy.shouldForceSocksDialOnLivenessSuspect()) {
            return
        }
        lastTunnelActivityMs = 0L
        schedulePeerClosedGrace(reason, graceMs)
        val p = activeParams ?: return
        scheduler.schedule({
            try {
                if (!_running.value || !_tunnelReady.value || !peerLivenessSuspect) return@schedule
                val ok = socksDialOnce(p, "www.gstatic.com", soTimeoutMs = 3_500) ||
                    socksDialOnce(p, "connectivitycheck.gstatic.com", soTimeoutMs = 3_000)
                if (ok) {
                    peerLivenessSuspect = false
                    healthFailStreak.set(0)
                    socksApiFailStreak.set(0)
                    DebugLog.i("Olcrtc", "suspect cleared by early dial ($reason)")
                    return@schedule
                }
                notifyPeerDead("socks_suspect:$reason")
            } catch (e: Exception) {
                DebugLog.w("Olcrtc", "suspect dial: ${e.message}")
            }
        }, graceMs.coerceAtLeast(1_500L), TimeUnit.MILLISECONDS)
    }

    private fun cancelPeerClosedGrace() {
        peerClosedGraceFuture?.cancel(false)
        peerClosedGraceFuture = null
        peerClosedPending = false
    }

    private fun cancelHealthWatch() {
        healthWatchFuture?.cancel(false)
        healthWatchFuture = null
    }

    /**
     * gstatic probe на узком Telemost/vp8 крадёт полосу у YouTube/Telegram
     * (секунды «буфера» / «появляется соединение»). Glitch не рестартит процесс —
     * зонд больше не запускаем.
     */
    private fun startSocksHealthWatch(params: Params) {
        cancelHealthWatch()
        if (!OlcrtcRecoveryPolicy.shouldProbeSocksWhileTunnelReady()) {
            DebugLog.i("Olcrtc", "SOCKS health probe off (${params.provider})")
            return
        }
        val periodSec = 45L
        healthWatchFuture = scheduler.scheduleWithFixedDelay({
            try {
                if (!_running.value || !_tunnelReady.value) return@scheduleWithFixedDelay
                if (!peerLivenessSuspect && hasRecentTunnelTraffic()) {
                    healthFailStreak.set(0)
                    return@scheduleWithFixedDelay
                }
                val ok = socksDialOnce(params, "www.gstatic.com", soTimeoutMs = 4_000) ||
                    socksDialOnce(params, "connectivitycheck.gstatic.com", soTimeoutMs = 3_500)
                if (ok) {
                    healthFailStreak.set(0)
                    streamDeadStreak.set(0)
                    socksApiFailStreak.set(0)
                    peerLivenessSuspect = false
                    return@scheduleWithFixedDelay
                }
                val n = healthFailStreak.incrementAndGet()
                val need = if (peerLivenessSuspect) 1 else 2
                if (n < need || (!peerLivenessSuspect && hasRecentTunnelTraffic())) {
                    WdttTunnelManager.logUi(
                        "olcrtc_health",
                        "SOCKS miss $n/$need (не kill)",
                        2,
                    )
                    return@scheduleWithFixedDelay
                }
                healthFailStreak.set(0)
                notifyPeerDead("socks_health_fail")
            } catch (e: Exception) {
                DebugLog.w("Olcrtc", "health watch: ${e.message}")
            }
        }, 45L, periodSec, TimeUnit.SECONDS)
    }

    private fun clearPrefetchCaches() {
        if (!OlcrtcRecoveryPolicy.shouldInvalidatePrefetchOnStop()) return
        telemostPrefetchCache?.file?.let { runCatching { it.delete() } }
        wbPrefetchCache?.file?.let { runCatching { it.delete() } }
        telemostPrefetchCache = null
        wbPrefetchCache = null
    }

    /**
     * Early fail (media timeout / code=1 до SOCKS): диск CONN_FILE протух —
     * следующий тумблер иначе снова 20с вхолостую на том же guest token.
     * Обычный stop/before_start CONN_FILE не трогаем (cold start).
     */
    private fun invalidateTelemostConnFile(reason: String) {
        telemostPrefetchCache?.file?.let { runCatching { it.delete() } }
        telemostPrefetchCache = null
        filesDirRef?.let { dir ->
            runCatching { File(dir, "telemost-conn.json").delete() }
        }
        WdttTunnelManager.logUi("olcrtc_tm_auth", "CONN_FILE wipe ($reason)", 2)
        DebugLog.i("Olcrtc", "CONN_FILE wipe: $reason")
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
                val force = peerLivenessSuspect &&
                    OlcrtcRecoveryPolicy.shouldForceSocksDialOnLivenessSuspect()
                val socksOk = probeSocksHealthy(forceDial = force)
                if (
                    OlcrtcRecoveryPolicy.shouldNotifyPeerDeadAfterGrace(
                        OlcrtcRecoveryPolicy.PeerClosedGraceInput(
                            running = _running.value,
                            iceConnected = iceConnected,
                            socksHealthy = socksOk,
                            recentTunnelTraffic = !force && hasRecentTunnelTraffic(),
                            forceLivenessCheck = force,
                        ),
                    )
                ) {
                    peerClosedPending = false
                    peerLivenessSuspect = false
                    notifyPeerDead(reason)
                } else {
                    peerClosedPending = false
                    if (!_running.value) return@schedule
                    when {
                        iceConnected -> {
                            peerLivenessSuspect = false
                            WdttTunnelManager.logUi("olcrtc_pc_ok", "peer восстановился сам", 2)
                        }
                        socksOk -> {
                            iceConnected = true
                            peerLivenessSuspect = false
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
                peerLivenessSuspect = false
                notifyPeerDead(reason)
            }
        }, graceMs, TimeUnit.MILLISECONDS)
    }

    private fun onPeerConnectedAgain() {
        iceConnected = true
        openStreamFailStreak.set(0)
        streamDeadStreak.set(0)
        socksApiFailStreak.set(0)
        peerLivenessSuspect = false
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
        if (!OlcrtcRecoveryPolicy.shouldRestartOnPeerGlitch(reason)) {
            DebugLog.w("Olcrtc", "peer glitch ignored (native reconnect): $reason")
            WdttTunnelManager.logUi(
                "olcrtc_keep_room",
                "сбой канала ($reason) — ждём восстановление без смены комнаты",
                2,
            )
            return
        }
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

    /** STUN/TURN hosts — плюс CIDR ниже (LiveKit/Yandex relay ≠ A-запись API). */
    private val TELEMOST_BYPASS_HOSTS = listOf(
        "turn.tel.yandex.net",
        "stun.rtc.yandex.net",
        "goloom.strm.yandex.net",
    )

    private val WBSTREAM_BYPASS_HOSTS = listOf(
        "stream.wb.ru",
        "stream-meetup.wildberries.ru",
        "rtc-el-01.wb.ru",
        "rtc-el-02.wb.ru",
    )

    /** Как PC sing-box direct: TURN relay часто на соседних IP, не на stream.wb.ru. */
    private val TELEMOST_BYPASS_CIDRS = listOf("37.9.0.0/16")
    private val WBSTREAM_BYPASS_CIDRS = listOf("185.62.192.0/18")

    /**
     * Telegram DC вне TUN — только для узкого Telemost/vp8 (иначе 149.154.*
     * душит YouTube). На WB stream канал шире → Telegram идёт через VPN
     * (иначе у ISP с DPI телега «не работает», а YT летает).
     */
    private val TELEGRAM_BYPASS_CIDRS = listOf(
        "149.154.160.0/20",
        "149.154.164.0/22",
        "91.108.4.0/22",
        "91.108.8.0/22",
        "91.108.12.0/22",
        "91.108.16.0/22",
        "91.108.56.0/22",
        "95.161.64.0/20",
    )

    private val TELEGRAM_DISALLOW_PACKAGES = listOf(
        "org.telegram.messenger",
        "org.telegram.messenger.web",
        "org.thunderdog.challegram",
        "org.telegram.plus",
    )

    /**
     * YouTube и Telegram оба через VPN (TM и WB).
     * Выкидывать TG с Telemost нельзя — пользователь ждёт оба через туннель.
     */
    private fun bypassTelegramOutsideTun(provider: String): Boolean = false

    /** Убить native/hev/TUN так же жёстко, как force-stop приложения. */
    fun hardReset(reason: String = "") {
        startEpoch.incrementAndGet()
        cancelPeerClosedGrace()
        cancelHealthWatch()
        openStreamFailStreak.set(0)
        streamDeadStreak.set(0)
        socksApiFailStreak.set(0)
        peerLivenessSuspect = false
        healthFailStreak.set(0)
        lastTunnelActivityMs = 0L
        activeParams = null
        suppressPeerDeadFor(5_000L)
        _tunnelReady.value = false
        _running.value = false
        starting.set(false)
        iceConnected = false
        peerLatched = false
        // CONN_FILE не трогаем на before_start — иначе каждый тумблер = полный Yandex auth.
        clearPrefetchCaches()
        val hadNative = olcrtcProc != null || tunBridgeProc != null || tunFd != null
        runCatching { HevSocksTunnel.stopIfLoaded() }
        killProc(tunBridgeProc, "tunBridge")
        tunBridgeProc = null
        killProc(olcrtcProc, "olcrtc")
        olcrtcProc = null
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
        // Слипы только если реально что-то убивали (cold start без leftover — без паузы).
        if (hadNative) {
            Thread.sleep(120)
            runCatching { HevSocksTunnel.stopIfLoaded() }
            Thread.sleep(80)
        }
        if (reason.isNotBlank()) {
            WdttTunnelManager.logUi("olcrtc_hard_reset_$reason", "hardReset: $reason", 2)
            DebugLog.w("Olcrtc", "hardReset: $reason")
        }
    }

    private fun killProc(proc: Process?, label: String) {
        if (proc == null) return
        try {
            proc.destroy()
            if (!proc.waitFor(1_200, TimeUnit.MILLISECONDS)) {
                proc.destroyForcibly()
                proc.waitFor(800, TimeUnit.MILLISECONDS)
            }
        } catch (e: Exception) {
            DebugLog.w("Olcrtc", "kill $label: ${e.message}")
            runCatching { proc.destroyForcibly() }
        }
    }

    fun stop(silent: Boolean = false) {
        if (!silent) {
            suppressPeerDeadFor(3_000L)
        } else {
            suppressPeerDeadFor(15_000L)
        }
        hardReset(if (silent) "stop_silent" else "stop")
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
        // Как kill app: полный native reset до смены Telemost↔WB.
        hardReset("before_start")
        val epoch = startEpoch.get()
        WdttTunnelManager.clearLogs()
        if (!starting.compareAndSet(false, true)) {
            return "olcrtc: already starting"
        }
        _lastError.value = null
        _tunnelReady.value = false
        iceConnected = false
        peerLatched = false
        if (params.cryptoKey.length != 64 || params.room.isBlank()) {
            starting.set(false)
            return "olcrtc: нужны room и crypto_key из /api/vpn/olcrtc2-config"
        }
        val useOlcrtc2 = params.olcrtc2
        val olcrtcBin =
            if (useOlcrtc2) {
                ensureOlcrtc2Binary(context)
                    ?: run {
                        starting.set(false)
                        return "olcrtc2: libolcrtc2.so не найден (собери build_olcrtc2_android.bat)"
                    }
            } else {
                ensureOlcrtcBinary(context)
                    ?: run {
                        starting.set(false)
                        return "olcrtc: libolcrtc.so не найден в nativeLibraryDir (jniLibs)"
                    }
            }

        // Per-session RFC1929: без auth любой локальный процесс жжёт peer (YourVPNDead).
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
        filesDirRef = appCtx.filesDir
        _running.value = true
        val engineHint = if (useOlcrtc2) "olcrtc2" else when (sessionParams.provider.lowercase()) {
            "wbstream" -> "livekit"
            "telemost" -> "goolom"
            else -> "goolom"
        }
        WdttTunnelManager.logUi(
            "olcrtc_start",
            "start ${sessionParams.provider} engine=$engineHint room=${sessionParams.room.take(36)}…",
            1,
        )

        worker.execute {
            try {
                if (epoch != startEpoch.get()) return@execute
                // Ещё раз на worker: предыдущий hev/proc могли дожить досюда.
                runCatching { HevSocksTunnel.stopIfLoaded() }
                killProc(olcrtcProc, "olcrtc_pre")
                olcrtcProc = null
                killProc(tunBridgeProc, "tunBridge_pre")
                tunBridgeProc = null
                try {
                    tunFd?.close()
                } catch (_: Exception) {
                }
                tunFd = null
                // Порт свободен сразу — не ждём 2с. Слип только если :8808 ещё слушает.
                run {
                    var busy = false
                    try {
                        Socket().use {
                            it.connect(
                                InetSocketAddress(sessionParams.socksHost, sessionParams.socksPort),
                                80,
                            )
                        }
                        busy = true
                    } catch (_: Exception) {
                    }
                    if (busy) {
                        Thread.sleep(80)
                        runCatching { HevSocksTunnel.stopIfLoaded() }
                        val deadline = System.currentTimeMillis() + 1_200
                        while (System.currentTimeMillis() < deadline) {
                            if (epoch != startEpoch.get()) return@execute
                            try {
                                Socket().use {
                                    it.connect(
                                        InetSocketAddress(sessionParams.socksHost, sessionParams.socksPort),
                                        80,
                                    )
                                }
                                Thread.sleep(60)
                            } catch (_: Exception) {
                                break
                            }
                        }
                    }
                }
                lastFailHint = ""
                iceConnected = false
                peerLatched = false
                _tunnelReady.value = false
                _running.value = true

                val dataDir = File(appCtx.filesDir, "olcrtc-data").apply { mkdirs() }
                val libDir = appCtx.applicationInfo.nativeLibraryDir
                val proc =
                    if (useOlcrtc2) {
                        DebugLog.i(
                            "Olcrtc",
                            "start olcrtc2 bin=$olcrtcBin room=${sessionParams.room.take(24)} socks=${sessionParams.socksHost}:${sessionParams.socksPort}",
                        )
                        // LTE: Go TLS к cloud-api.yandex.ru часто мёртв — как v1:
                        // OkHttp whitelist → OLCRTC_TELEMOST_CONN_FILE + STATIC_HOSTS.
                        val staticHosts = linkedMapOf<String, String>()
                        var telemostConnFile: File? = null
                        var wbConnFile: File? = null
                        when {
                            sessionParams.provider.equals("telemost", ignoreCase = true) -> {
                                telemostConnFile =
                                    prefetchTelemostConnViaOkHttp(appCtx, sessionParams.room, staticHosts)
                                resolveInto(
                                    staticHosts,
                                    "cloud-api.yandex.ru",
                                    "cloud-api.yandex.net",
                                    "telemost.yandex.ru",
                                    "goloom.strm.yandex.net",
                                    "stun.rtc.yandex.net",
                                    "turn.tel.yandex.net",
                                    "api.messenger.yandex.net",
                                )
                            }
                            sessionParams.provider.equals("wbstream", ignoreCase = true) -> {
                                wbConnFile =
                                    prefetchWbstreamConnViaOkHttp(appCtx, sessionParams.room, staticHosts)
                                resolveInto(
                                    staticHosts,
                                    "stream.wb.ru",
                                    "rtc-el-02.wb.ru",
                                    "rtc-el-01.wb.ru",
                                )
                            }
                        }
                        lastStaticHostIps = staticHosts.toMap()
                        if (telemostConnFile == null &&
                            sessionParams.provider.equals("telemost", ignoreCase = true)
                        ) {
                            WdttTunnelManager.logUi(
                                "olcrtc2_tm_prefetch",
                                "OkHttp auth fail — Go сам пойдёт на cloud-api (на LTE часто code=1)",
                                3,
                                isError = true,
                            )
                        }
                        startOlcrtc2Process(
                            appCtx,
                            olcrtcBin,
                            dataDir,
                            libDir,
                            sessionParams,
                            telemostConnFile = telemostConnFile,
                            wbConnFile = wbConnFile,
                            staticHosts = staticHosts,
                            dnsHostPort = systemDnsHostPort(appCtx),
                        )
                    } else {
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
                        resolveInto(staticHosts, "stream.wb.ru", "goloom.strm.yandex.net", "rtc-el-02.wb.ru")
                        lastStaticHostIps = staticHosts.toMap()
                        startOlcrtcProcess(
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
                    }
                olcrtcProc = proc
                pipeLogs(proc)
                watchExit(proc, epoch)

                // Telemost: SOCKS слушает только после peer latch. 90с = минуты на мёртвом CONN_FILE.
                val socksWaitMs =
                    if (sessionParams.provider.equals("telemost", ignoreCase = true)) 12_000L
                    else 90_000L
                if (!waitForSocks(sessionParams.socksHost, sessionParams.socksPort, socksWaitMs, proc, epoch)) {
                    val exited = try {
                        proc.exitValue()
                    } catch (_: Exception) {
                        null
                    }
                    val msg = when {
                        lastFailHint.isNotBlank() -> lastFailHint
                        exited != null ->
                            "olcrtc вышел code=$exited до SOCKS (бинарь/room/peer)"
                        else ->
                            "olcrtc SOCKS не поднялся на ${sessionParams.socksHost}:${sessionParams.socksPort}"
                    }
                    if (epoch == startEpoch.get()) {
                        markStartFailed(msg)
                        WdttTunnelManager.logUi("olcrtc_socks_fail", msg, 99, isError = true)
                    }
                    return@execute
                }
                WdttTunnelManager.logUi(
                    "olcrtc_socks",
                    "SOCKS listen ${sessionParams.socksHost}:${sessionParams.socksPort}",
                    1,
                )
                // Telemost Wi‑Fi: ICE обычно за 2–5с. 25с держали тумблер при живом SOCKS.
                val peerWaitMs =
                    if (sessionParams.provider.equals("telemost", ignoreCase = true)) 8_000L
                    else 25_000L
                WdttTunnelManager.logUi(
                    "olcrtc_dial_wait",
                    "ждём ICE/peer… provider=${sessionParams.provider} max=${peerWaitMs / 1000}с",
                    1,
                )
                if (!waitForPeerReady(sessionParams, peerWaitMs, proc, epoch)) {
                    val msg = if (lastFailHint.isNotBlank()) {
                        lastFailHint
                    } else {
                        "olcrtc: peer/ICE не поднялся (dial timeout)"
                    }
                    if (epoch == startEpoch.get()) {
                        markStartFailed(msg)
                        WdttTunnelManager.logUi("olcrtc_dial_fail", msg, 99, isError = true)
                    }
                    return@execute
                }
                WdttTunnelManager.logUi(
                    "olcrtc_dial",
                    if (peerLatched) "peer ready (latched)"
                    else if (iceConnected) "peer ready (ICE)"
                    else "peer ready (SOCKS dial fallback)",
                    1,
                )
                iceConnected = true
                val tHev = System.currentTimeMillis()
                if (vpnService != null) {
                    val tunErr = attachHevTun(appCtx, sessionParams, vpnService)
                    if (tunErr != null) {
                        if (epoch == startEpoch.get()) {
                            markStartFailed(tunErr)
                            WdttTunnelManager.logUi("olcrtc_tun_fail", tunErr, 99, isError = true)
                        }
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
                WdttTunnelManager.logUi(
                    "olcrtc_hev_ms",
                    "hev+exclude ${System.currentTimeMillis() - tHev}ms",
                    2,
                )
                Thread.sleep(40)
                if (epoch != startEpoch.get()) return@execute
                _tunnelReady.value = true
                WdttTunnelManager.logUi("olcrtc_ready", "tunnelReady (SOCKS + hev TUN)", 1)
                startSocksHealthWatch(sessionParams)
                // Не блокируем ready: прогрев первой загрузки в фоне (Android+PC parity).
                worker.execute {
                    if (epoch != startEpoch.get()) return@execute
                    runCatching { warmFirstLoadPath(sessionParams, epoch) }
                }
            } catch (e: Exception) {
                val msg = e.message ?: "olcrtc background start failed"
                if (epoch == startEpoch.get()) {
                    markStartFailed(msg)
                    WdttTunnelManager.logUi("olcrtc_bg_fail", msg, 99, isError = true)
                    DebugLog.e("Olcrtc", "bg start failed", e)
                }
            } finally {
                if (epoch == startEpoch.get()) starting.set(false)
            }
        }
        return null
    }

    /** Ранний fail: сбрасываем running сразу — иначе UI «Подключение…» и recover зависают. */
    private fun markStartFailed(msg: String) {
        if (!_tunnelReady.value) {
            invalidateTelemostConnFile("start_failed:${msg.take(40)}")
        }
        hardReset("start_failed")
        _lastError.value = msg
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
                        if (
                            l.contains("peer latched", ignoreCase = true) ||
                            l.contains("SOCKS5 server listening", ignoreCase = true) ||
                            Regex("""session\s+\S+\s+opened""", RegexOption.IGNORE_CASE).containsMatchIn(l)
                        ) {
                            peerLatched = true
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
                            l.contains("failed to connect link", ignoreCase = true) ||
                            l.contains("handshake on reconnect failed", ignoreCase = true) ||
                            l.contains("control missed pong", ignoreCase = true)
                        ) {
                            if (!_tunnelReady.value &&
                                (
                                    l.contains("subscriber media timeout", ignoreCase = true) ||
                                        l.contains("failed to connect link", ignoreCase = true)
                                    )
                            ) {
                                invalidateTelemostConnFile("media_timeout_before_ready")
                            }
                            markPeerLivenessSuspect(
                                when {
                                    l.contains("missed pong", ignoreCase = true) -> "missed_pong"
                                    l.contains("handshake", ignoreCase = true) -> "handshake_fail"
                                    else -> "media_timeout"
                                },
                                graceMs = 8_000L,
                            )
                        }
                        if (l.contains("OpenStream failed", ignoreCase = true) && _tunnelReady.value) {
                            // Под нагрузкой (speedtest) OpenStream fail нормален — не escalate если трафик идёт.
                            if (hasRecentTunnelTraffic() && !peerLivenessSuspect) {
                                openStreamFailStreak.set(0)
                            } else {
                                val nFail = openStreamFailStreak.incrementAndGet()
                                if (nFail >= 6) {
                                    openStreamFailStreak.set(0)
                                    markPeerLivenessSuspect("openstream_timeout", 5_000L)
                                }
                            }
                        } else if (
                            l.contains("tunnel to ", ignoreCase = true) ||
                            l.contains("Link connected", ignoreCase = true)
                        ) {
                            // Half-dead peer: редкие «tunnel to» при flood remote-not-ready.
                            // Не сбрасываем streamDeadStreak / suspect — иначе зелёный вис.
                            lastTunnelActivityMs = System.currentTimeMillis()
                            openStreamFailStreak.set(0)
                        }
                        // remote not ready / sid timeout при ready → зелёный вис (даже если
                        // иногда проскакивает tunnel to). Считаем всегда, traffic не сбрасывает.
                        if (
                            _tunnelReady.value &&
                            (
                                l.contains("remote not ready", ignoreCase = true) ||
                                    (
                                        l.contains("connect failed: sid=", ignoreCase = true) &&
                                            l.contains("timeout", ignoreCase = true)
                                        )
                                )
                        ) {
                            val n = streamDeadStreak.incrementAndGet()
                            if (n >= OlcrtcRecoveryPolicy.STREAM_DEAD_KILL_STREAK) {
                                streamDeadStreak.set(0)
                                notifyPeerDead("stream_dead_flood")
                            } else if (
                                n >= OlcrtcRecoveryPolicy.STREAM_DEAD_SUSPECT_STREAK &&
                                !peerLivenessSuspect
                            ) {
        markPeerLivenessSuspect("stream_dead", OlcrtcRecoveryPolicy.PEER_CLOSED_GRACE_MS)
                            }
                        }
                        if (Regex(
                                """\[ice\] TRACE|\[sctp\] TRACE|bufferedAmount|service-unavailable|extdisco|disco_1|\[xmpp|Failed to send packet|operation not permitted|Failed to ping without candidate|Failed to listen udp|fe80:|%dummy0|use of closed network connection""",
                                RegexOption.IGNORE_CASE,
                            ).containsMatchIn(l)
                        ) {
                            continue
                        }
                        // Типичный шум Telemost/WB: часть TURN allocate/TLS fail при живом peer.
                        val iceNoise = Regex(
                            """failed to allocate on TURN|failed to get server reflexive|all retransmissions failed|i/o timeout.*stun:|stun:turn\.tel\.yandex|turn\.tel\.yandex\.net|Failed to connect to relay|Failed to read from candidate|certificate has expired|x509: certificate|not yet valid|Failed to find pair for add binding|add binding response|related :::""",
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

    private fun watchExit(proc: Process, epoch: Int) {
        Thread({
            try {
                val code = proc.waitFor()
                if (epoch != startEpoch.get()) {
                    DebugLog.i("Olcrtc", "ignore exit after reset code=$code epoch=$epoch now=${startEpoch.get()}")
                    return@Thread
                }
                // Важно: после stop() olcrtcProc=null — всё равно это СТАРЫЙ процесс.
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

    /** Меню DNS → VpnService, когда mapdns выключен. */
    private fun resolveOlcrtcDnsServers(context: Context): List<String> =
        DnsSettings.ipv4Servers(context)

    /**
     * TUN → SOCKS: IPv4-only, mapdns/fake-ip, udp→tcp (блок QUIC), TG+YT via VPN.
     *
     * mapdns: приложение получает fake IP без сетевого запроса, а в SOCKS CONNECT
     * уходит домен → резолвит olcrtc2-srv на соте. Без него каждый холодный домен
     * стоил round-trip через VP8-несущую — отсюда медленная первая загрузка.
     *
     * Пул fake IP — 198.19.0.0/16, а не дефолтный hev 100.64.0.0/10: на LTE это
     * CGNAT оператора, и пересечение ломало ICE/TURN (прошлый откат mapdns).
     */
    private fun attachHevTun(context: Context, params: Params, vpnService: VpnService): String? {
        if (!HevSocksTunnel.ensureLoaded()) {
            return "libhev-socks5-tunnel.so не загружен"
        }
        runCatching { HevSocksTunnel.stopIfLoaded() }
        try {
            tunFd?.close()
        } catch (_: Exception) {
        }
        tunFd = null
        Thread.sleep(50)
        val menuDns = resolveOlcrtcDnsServers(context).ifEmpty { listOf("77.88.8.8", "77.88.8.1") }
        val tgOutside = bypassTelegramOutsideTun(params.provider)
        val conf = File(context.filesDir, "hev-olcrtc.yml")
        val hevYaml = buildString {
            appendLine("tunnel:")
            appendLine("  mtu: 1400")
            appendLine("  ipv4: 198.18.0.1")
            appendLine("socks5:")
            appendLine("  port: ${params.socksPort}")
            appendLine("  address: ${params.socksHost}")
            appendLine("  udp: 'tcp'")
            if (params.socksUser.isBlank() || params.socksPass.isBlank()) {
                return "olcrtc SOCKS: нужны user/pass (RFC1929)"
            }
            val u = params.socksUser.replace("'", "''")
            val p = params.socksPass.replace("'", "''")
            appendLine("  username: '$u'")
            appendLine("  password: '$p'")
            if (OLCRTC2_MAPDNS) {
                appendLine("mapdns:")
                appendLine("  address: $MAPDNS_ADDRESS")
                appendLine("  port: 53")
                appendLine("  network: $MAPDNS_NETWORK")
                appendLine("  netmask: $MAPDNS_NETMASK")
                appendLine("  cache-size: 10000")
            }
            appendLine("misc:")
            appendLine("  log-level: warn")
            appendLine("  connect-timeout: 3500")
            appendLine("  tcp-read-write-timeout: 300000")
            appendLine("  udp-read-write-timeout: 400")
        }
        conf.writeText(hevYaml)
        WdttTunnelManager.logUi(
            "olcrtc_hev_udp",
            if (OLCRTC2_MAPDNS) {
                "hev UDP→TCP (блок QUIC; mapdns $MAPDNS_NETWORK; TG+YT via VPN)"
            } else {
                "hev UDP→TCP (блок QUIC; DNS=real; TG+YT via VPN)"
            },
            2,
        )
        return try {
            val builder = vpnService.Builder()
                .setSession("Silent olcrtc")
                .setMtu(1400)
                .addAddress("198.18.0.1", 30)
                .addRoute("0.0.0.0", 0)
            runCatching { builder.allowFamily(OsConstants.AF_INET) }
            if (OLCRTC2_MAPDNS) {
                runCatching { builder.addDnsServer(MAPDNS_ADDRESS) }
            } else {
                for (dns in menuDns) {
                    runCatching { builder.addDnsServer(dns) }
                }
            }
            WdttTunnelManager.logUi(
                "olcrtc_tun",
                if (OLCRTC2_MAPDNS) {
                    "IPv4-only + mapdns $MAPDNS_ADDRESS (${params.provider}; " +
                        "меню DNS не применяется — резолв на соте)"
                } else {
                    "IPv4-only + DNS=real (${params.provider}; ${menuDns.joinToString(",")})"
                },
                2,
            )
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                val excludeHosts = linkedSetOf<String>()
                // Системный DNS вне TUN — fallback для приложений, игнорирующих VPN DNS.
                excludeHosts.addAll(systemDnsIpv4Hosts(context))
                if (!OLCRTC2_MAPDNS) {
                    excludeHosts.addAll(menuDns)
                }
                val bypassCidrs: List<String>
                if (params.provider.equals("telemost", ignoreCase = true)) {
                    excludeHosts.addAll(TELEMOST_BYPASS_HOSTS)
                    bypassCidrs = TELEMOST_BYPASS_CIDRS
                } else if (params.provider.equals("wbstream", ignoreCase = true)) {
                    excludeHosts.addAll(WBSTREAM_BYPASS_HOSTS)
                    bypassCidrs = WBSTREAM_BYPASS_CIDRS
                } else {
                    bypassCidrs = emptyList()
                }
                // Prefetch STATIC_HOSTS — /32 без повторного DNS.
                for (ip in lastStaticHostIps.values) {
                    if (ip.matches(Regex("""^\d{1,3}(\.\d{1,3}){3}$"""))) {
                        excludeHosts.add(ip)
                    }
                }
                var excluded = 0
                for (host in excludeHosts) {
                    excluded += excludeHostRoutes(builder, host)
                }
                val cidrN = excludeCidrRoutes(builder, bypassCidrs)
                excluded += cidrN
                WdttTunnelManager.logUi(
                    "olcrtc_tun_excl",
                    "excludeRoute hosts=${excludeHosts.size} cidrs=$cidrN ips≈$excluded " +
                        "tgCidr=0 tgVia=vpn mapdns=${if (OLCRTC2_MAPDNS) MAPDNS_NETWORK else "off"}",
                    2,
                )
            } else {
                WdttTunnelManager.logUi(
                    "olcrtc_tun_excl",
                    "API<33: без excludeRoute (только disallow app) — ICE/TURN на OEM может ломаться",
                    3,
                )
            }
            runCatching { builder.addDisallowedApplication(context.packageName) }
            disallowOemNoiseFromVpn(builder, context)
            if (tgOutside) {
                disallowTelegramFromVpn(builder, context)
            } else {
                WdttTunnelManager.logUi(
                    "olcrtc_tun_tg",
                    "Telegram via VPN (provider=${params.provider})",
                    2,
                )
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                runCatching { builder.setMetered(false) }
            }
            val underlyingNet = runCatching {
                context.getSystemService(ConnectivityManager::class.java)?.activeNetwork
            }.getOrNull()
            val pfd = builder.establish()
                ?: return "VpnService.Builder.establish() вернул null"
            tunFd = pfd
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
                if (OLCRTC2_MAPDNS) {
                    "hev TUN ok fd=${pfd.fd} mapdns=fake-ip (резолв домена на соте)"
                } else {
                    "hev TUN ok fd=${pfd.fd} DNS=real (mapdns off)"
                },
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

    /**
     * Только шумные push/analytics OEM — не весь `com.vivo.*` (иначе ~180 pkgs,
     * браузер/webview OEM уходят мимо VPN → «туннель ок, сайты нет»).
     */
    private fun disallowOemNoiseFromVpn(builder: VpnService.Builder, context: Context) {
        val exact = listOf(
            "com.vivo.pushservice",
            "com.vivo.abe",
            "com.vivo.daemonService",
            "com.bbk.account",
            "com.huawei.hwid",
            "com.huawei.android.pushagent",
            "com.miui.analytics",
            "com.xiaomi.xmsf",
            "com.coloros.mcssdk",
            "com.heytap.mcs",
            "com.oplus.mcs",
        )
        var n = 0
        for (pkg in exact) {
            if (pkg == context.packageName) continue
            runCatching {
                context.packageManager.getApplicationInfo(pkg, 0)
                builder.addDisallowedApplication(pkg)
                n++
            }
        }
        if (n > 0) {
            WdttTunnelManager.logUi("olcrtc_tun_oem", "disallow OEM noise pkgs=$n (vp8 budget→YouTube)", 2)
        }
    }

    private fun disallowTelegramFromVpn(builder: VpnService.Builder, context: Context) {
        var n = 0
        for (pkg in TELEGRAM_DISALLOW_PACKAGES) {
            runCatching {
                context.packageManager.getApplicationInfo(pkg, 0)
                builder.addDisallowedApplication(pkg)
                n++
            }
        }
        if (n > 0) {
            WdttTunnelManager.logUi("olcrtc_tun_tg", "disallow Telegram pkgs=$n (direct, не vp8)", 2)
        }
    }

    /** CIDR → excludeRoute (API 33+). */
    private fun excludeCidrRoutes(builder: VpnService.Builder, cidrs: List<String>): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return 0
        var n = 0
        for (cidr in cidrs) {
            val parts = cidr.split("/")
            if (parts.size != 2) continue
            val ip = parts[0]
            val prefix = parts[1].toIntOrNull() ?: continue
            val addr = runCatching { InetAddress.getByName(ip) }.getOrNull() ?: continue
            if (addr.address?.size != 4) continue
            runCatching {
                builder.excludeRoute(IpPrefix(addr, prefix))
                n++
            }
        }
        return n
    }

    /** Resolve host → excludeRoute /32 для каждого A-записи (API 33+). */
    private fun excludeHostRoutes(builder: VpnService.Builder, host: String): Int {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return 0
        val seen = linkedSetOf<String>()
        fun excludeIp(ip: String) {
            if (ip.isBlank() || ip.contains(':') || !seen.add(ip)) return
            val addr = runCatching { InetAddress.getByName(ip) }.getOrNull() ?: return
            if (addr.address?.size != 4) {
                seen.remove(ip)
                return
            }
            runCatching { builder.excludeRoute(IpPrefix(addr, 32)) }
                .onFailure { seen.remove(ip) }
        }
        if (host.matches(Regex("""^\d{1,3}(\.\d{1,3}){3}$"""))) {
            excludeIp(host)
            return seen.size
        }
        // Prefetch + полный DNS (TURN/STUN multi-A). Только STATIC → ips≈1/host → peer мёртв после TUN.
        lastStaticHostIps[host]?.let { excludeIp(it) }
        runCatching { InetAddress.getAllByName(host) }.getOrNull()?.forEach { addr ->
            if (addr.address?.size == 4) {
                addr.hostAddress?.let { excludeIp(it) }
            }
        }
        return seen.size
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

    /**
     * Peer готов до TUN: ICE/peer latched из логов native.
     * gstatic-цикл здесь не нужен — на Telemost это секунды холостого трафика
     * до первого YouTube (каждый fail = до 4с).
     * Fallback: один короткий dial только если ICE так и не пришёл.
     */
    private fun waitForPeerReady(
        params: Params,
        timeoutMs: Long,
        proc: Process? = null,
        epoch: Int = startEpoch.get(),
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (epoch != startEpoch.get()) return false
            if (proc != null && !isProcessAlive(proc)) return false
            if (!_running.value) return false
            if (iceConnected || peerLatched) return true
            Thread.sleep(120)
        }
        if (iceConnected || peerLatched) return true
        WdttTunnelManager.logUi(
            "olcrtc_dial_fallback",
            "ICE не пришёл за ${timeoutMs / 1000}с — один SOCKS dial",
            2,
        )
        return socksDialOnce(params, "www.gstatic.com", soTimeoutMs = 2_500)
    }

    /** @deprecated оставлен для тестов/совместимости — см. [waitForPeerReady]. */
    private fun waitForSocksDial(
        params: Params,
        timeoutMs: Long,
        proc: Process? = null,
        epoch: Int = startEpoch.get(),
    ): Boolean = waitForPeerReady(params, timeoutMs, proc, epoch)

    /**
     * После tunnelReady: короткий прогрев нескольких доменов.
     *
     * Один dial (`i.ytimg.com`) не всегда успевает «раскачать» vp8channel/KCP, поэтому
     * первый реальный сайт может ждать 8–12с. Делаем 1 мягкую волну коротких
     * SOCKS CONNECT (без блокировки UI), чтобы убрать «пустую паузу» на первой загрузке.
     *
     * Важно: не используем gstatic/google в warm (их уже убирали как шум/регрессию).
     */
    private fun warmFirstLoadPath(params: Params, epoch: Int) {
        val hosts =
            linkedSetOf(
                "www.cloudflare.com",
                "i.ytimg.com",
                "www.youtube.com",
            )
        // Для WB полезно прогреть и его CDN/API путь.
        if (params.provider.equals("wbstream", ignoreCase = true)) {
            hosts.add("stream.wb.ru")
            hosts.add("wildberries.ru")
        }
        val rounds = 1
        val perDialTimeoutMs = 1200
        for (round in 1..rounds) {
            if (epoch != startEpoch.get() || !_running.value || !_tunnelReady.value) return
            for (host in hosts) {
                if (epoch != startEpoch.get() || !_running.value || !_tunnelReady.value) return
                runCatching { socksDialOnce(params, host, soTimeoutMs = perDialTimeoutMs) }
            }
            if (round != rounds) {
                Thread.sleep(120)
            }
        }
        WdttTunnelManager.logUi(
            "olcrtc_warm",
            "first-load warm done (${hosts.size} hosts × $rounds)",
            2,
        )
    }

    /**
     * TCP через локальный SOCKS5 (RFC1929) к destHost:destPort.
     * Для HTTP API с LTE: app в disallow → underlying режется whitelist,
     * а HTTP через SOCKS идёт peer → exit → nip.io.
     */
    fun openSocksTcp(
        destHost: String,
        destPort: Int,
        soTimeoutMs: Int = 12_000,
    ): Socket? {
        val p = activeParams ?: return null
        if (!_tunnelReady.value || !_running.value) return null
        if (destHost.isBlank() || destPort !in 1..65535) return null
        return try {
            socksConnect(p, destHost, destPort, soTimeoutMs)
        } catch (e: Exception) {
            DebugLog.w("OlcrtcTunnel", "openSocksTcp ${e.javaClass.simpleName}: ${e.message}")
            null
        }
    }

    /** SOCKS5 CONNECT + optional RFC1929 user/pass (probe: connect then close). */
    private fun socksDialOnce(
        params: Params,
        domain: String,
        soTimeoutMs: Int,
        destPort: Int = 443,
    ): Boolean {
        return try {
            socksConnect(params, domain, destPort, soTimeoutMs)?.use { true } ?: false
        } catch (_: Exception) {
            false
        }
    }

    /** SOCKS5 CONNECT; caller owns returned Socket. */
    private fun socksConnect(
        params: Params,
        domain: String,
        destPort: Int,
        soTimeoutMs: Int,
    ): Socket? {
        val host = params.socksHost.ifBlank { "127.0.0.1" }
        val port = params.socksPort
        val ipv4 = runCatching {
            val m = Regex("""^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$""").matchEntire(domain.trim())
            if (m == null) null
            else {
                val octets = m.groupValues.drop(1).map { it.toInt() }
                if (octets.all { it in 0..255 }) octets.map { it.toByte() }.toByteArray() else null
            }
        }.getOrNull()
        val domainBytes = if (ipv4 == null) domain.toByteArray(Charsets.US_ASCII) else null
        if (ipv4 == null && (domainBytes == null || domainBytes.isEmpty() || domainBytes.size > 255)) {
            return null
        }
        val needAuth = params.socksUser.isNotBlank()
        return try {
            val s = Socket()
            s.soTimeout = soTimeoutMs
            s.connect(InetSocketAddress(host, port), 2_000)
            val out = s.getOutputStream()
            val inp = s.getInputStream()
            out.write(
                if (needAuth) byteArrayOf(0x05, 0x01, 0x02) else byteArrayOf(0x05, 0x01, 0x00),
            )
            val greet = ByteArray(2)
            if (inp.read(greet) < 2 || greet[0] != 0x05.toByte()) {
                s.close()
                return null
            }
            if (needAuth) {
                if (greet[1] != 0x02.toByte()) {
                    s.close()
                    return null
                }
                val ub = params.socksUser.toByteArray(Charsets.UTF_8)
                val pb = params.socksPass.toByteArray(Charsets.UTF_8)
                if (ub.size > 255 || pb.size > 255) {
                    s.close()
                    return null
                }
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
                    s.close()
                    return null
                }
            } else if (greet[1] != 0x00.toByte()) {
                s.close()
                return null
            }
            val req = if (ipv4 != null) {
                val r = ByteArray(4 + 4 + 2)
                r[0] = 0x05
                r[1] = 0x01
                r[3] = 0x01
                System.arraycopy(ipv4, 0, r, 4, 4)
                r[8] = ((destPort ushr 8) and 0xff).toByte()
                r[9] = (destPort and 0xff).toByte()
                r
            } else {
                val db = domainBytes!!
                val r = ByteArray(5 + db.size + 2)
                r[0] = 0x05
                r[1] = 0x01
                r[3] = 0x03
                r[4] = db.size.toByte()
                System.arraycopy(db, 0, r, 5, db.size)
                val p = 5 + db.size
                r[p] = ((destPort ushr 8) and 0xff).toByte()
                r[p + 1] = (destPort and 0xff).toByte()
                r
            }
            out.write(req)
            val resp = ByteArray(10)
            var n = 0
            while (n < 4) {
                val r = inp.read(resp, n, 4 - n)
                if (r < 0) {
                    s.close()
                    return null
                }
                n += r
            }
            if (resp[1] != 0x00.toByte()) {
                s.close()
                return null
            }
            val atyp = resp[3].toInt() and 0xff
            val rest = when (atyp) {
                0x01 -> 4 + 2
                0x03 -> {
                    val lenB = ByteArray(1)
                    if (inp.read(lenB) < 1) {
                        s.close()
                        return null
                    }
                    (lenB[0].toInt() and 0xff) + 2
                }
                0x04 -> 16 + 2
                else -> {
                    s.close()
                    return null
                }
            }
            var skip = 0
            val buf = ByteArray(rest.coerceAtMost(64))
            while (skip < rest) {
                val r = inp.read(buf, 0, (rest - skip).coerceAtMost(buf.size))
                if (r < 0) {
                    s.close()
                    return null
                }
                skip += r
            }
            s
        } catch (_: Exception) {
            null
        }
    }

    /**
     * После SOCKS CONNECT шлём TLS ClientHello — иначе peer может ACK CONNECT,
     * а полезная нагрузка (Chrome/YouTube) уже мёртва.
     */
    private fun socksTlsProbe(params: Params, domain: String, soTimeoutMs: Int): Boolean {
        val domainBytes = domain.toByteArray(Charsets.US_ASCII)
        if (domainBytes.size > 255) return false
        val needAuth = params.socksUser.isNotBlank()
        return try {
            Socket().use { s ->
                s.soTimeout = soTimeoutMs
                s.connect(InetSocketAddress(params.socksHost, params.socksPort), 800)
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
                req[p + 1] = 0xBB.toByte()
                out.write(req)
                // VER REP RSV ATYP (+ bind addr). Читаем минимум заголовок + IPv4 bind.
                val hdr = ByteArray(4)
                if (inp.read(hdr) < 4 || hdr[1] != 0x00.toByte()) return false
                when (hdr[3].toInt() and 0xff) {
                    0x01 -> {
                        val skip = ByteArray(4 + 2)
                        if (inp.read(skip) < skip.size) return false
                    }
                    0x03 -> {
                        val lenBuf = ByteArray(1)
                        if (inp.read(lenBuf) < 1) return false
                        val skip = ByteArray((lenBuf[0].toInt() and 0xff) + 2)
                        if (inp.read(skip) < skip.size) return false
                    }
                    0x04 -> {
                        val skip = ByteArray(16 + 2)
                        if (inp.read(skip) < skip.size) return false
                    }
                    else -> return false
                }
                // Minimal TLS1.0 ClientHello (record type 0x16)
                val hello = byteArrayOf(
                    0x16, 0x03, 0x01, 0x00, 0x2e,
                    0x01, 0x00, 0x00, 0x2a, 0x03, 0x03,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                    0x00, 0x00, 0x01, 0x00, 0x00, 0x2f, 0x01, 0x00,
                )
                out.write(hello)
                out.flush()
                val first = inp.read()
                // 0x16 ServerHello / 0x15 alert — оба значат, что байты дошли через peer.
                first == 0x16 || first == 0x15
            }
        } catch (_: Exception) {
            false
        }
    }

    fun startFromConfigJson(context: Context, json: String, vpnService: VpnService? = null): String? {
        cachedConfigJson = json
        val obj = JSONObject(json)
        val family = obj.optString("bypassFamily", obj.optString("bypass_family", "olcrtc2"))
        val svc = vpnService ?: (context as? VpnService)
        return start(
            context,
            Params(
                provider = obj.optString("olcrtc_provider", "telemost"),
                room = obj.optString("olcrtc_room"),
                cryptoKey = obj.optString("olcrtc_crypto_key"),
                transport = obj.optString("olcrtc_transport", "vp8channel"),
                socksHost = obj.optString("olcrtc_socks_host", "127.0.0.1"),
                socksPort = obj.optInt("olcrtc_socks_port", 8808),
                isBootstrap = obj.optBoolean("is_bootstrap", false),
                httpsProxy = obj.optString("olcrtc_https_proxy", ""),
                authToken = obj.optString("olcrtc_auth_token", ""),
                olcrtc2 = family != "olcrtc",
            ),
            vpnService = svc,
        )
    }

    private fun ensureOlcrtc2Binary(ctx: Context): String? {
        val abi = android.os.Build.SUPPORTED_ABIS.firstOrNull().orEmpty()
        val so = File(ctx.applicationInfo.nativeLibraryDir, "libolcrtc2.so")
        if (!so.exists() || so.length() == 0L) {
            DebugLog.e("Olcrtc", "libolcrtc2.so missing in ${ctx.applicationInfo.nativeLibraryDir}")
            WdttTunnelManager.logUi(
                "olcrtc2_bin_missing",
                "libolcrtc2.so missing nativeLibraryDir abi=$abi",
                99,
                isError = true,
            )
            return null
        }
        WdttTunnelManager.logUi(
            "olcrtc2_bin",
            "binary ok size=${so.length()} abi=$abi path=native/${so.name}",
            1,
        )
        return so.absolutePath
    }

    private fun startOlcrtc2Process(
        context: Context,
        bin: String,
        dataDir: File,
        libDir: String,
        params: Params,
        telemostConnFile: File? = null,
        wbConnFile: File? = null,
        staticHosts: Map<String, String> = emptyMap(),
        dnsHostPort: String = "1.1.1.1:53",
    ): Process {
        val socks = "${params.socksHost}:${params.socksPort}"
        val mode = when {
            params.provider.equals("wbstream", ignoreCase = true) -> "wbstream"
            else -> "telemost"
        }
        WdttTunnelManager.logUi("olcrtc2_exec", "exec native/${File(bin).name} mode=$mode socks=$socks", 2)
        return ProcessBuilder(listOf(bin)).apply {
            directory(dataDir)
            redirectErrorStream(true)
            environment()["LD_LIBRARY_PATH"] = libDir
            environment()["OLCRTC2_MODE"] = mode
            environment()["OLCRTC2_ROOM"] = params.room
            environment()["OLCRTC2_KEY"] = params.cryptoKey
            environment()["OLCRTC2_SOCKS"] = socks
            environment()["OLCRTC2_DNS"] = dnsHostPort
            if (params.socksUser.isNotBlank()) {
                environment()["OLCRTC2_SOCKS_USER"] = params.socksUser
                environment()["OLCRTC2_SOCKS_PASS"] = params.socksPass
            }
            // vendor auth/telemost читает те же env, что и olcrtc v1
            telemostConnFile?.takeIf { it.isFile }?.let {
                environment()["OLCRTC_TELEMOST_CONN_FILE"] = it.absolutePath
                WdttTunnelManager.logUi(
                    "olcrtc2_tm_prefetch",
                    "CONN_FILE=${it.name} (OkHttp, без Go→cloud-api)",
                    1,
                )
            }
            wbConnFile?.takeIf { it.isFile }?.let {
                // Не ставим OLCRTC_WBSTREAM_CONN_FILE: LiveKit roomToken из OkHttp
                // короткоживущий → peer мрёт через минуты. STATIC_HOSTS + excludeRoute
                // дают Go самому сделать guest (как PC при 498).
                WdttTunnelManager.logUi(
                    "olcrtc2_wb_prefetch",
                    "WB hosts only (без CONN_FILE — Go guest сам)",
                    1,
                )
            }
            if (staticHosts.isNotEmpty()) {
                environment()["OLCRTC_STATIC_HOSTS"] =
                    staticHosts.entries.joinToString(";") { "${it.key}=${it.value}" }
                WdttTunnelManager.logUi(
                    "olcrtc2_dns",
                    "STATIC_HOSTS=${staticHosts.size} (Java DNS → Go dial)",
                    2,
                )
            }
        }.start()
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
            // 1) Живой Silent VPN (app excluded) → signaling через туннель.
            // 2) Иначе underlying Wi‑Fi/LTE (не VPN), чтобы OkHttp не ушёл в 0.0.0.0/0
            //    мёртвого hev/WG и не получил timeout к cloud-api на мобильном.
            val net = VpnNetworkHelper.getSilentVpnNetwork(context)
                ?: cm?.allNetworks?.firstOrNull { n ->
                    val caps = cm.getNetworkCapabilities(n) ?: return@firstOrNull false
                    !caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) &&
                        caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                        (
                            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
                                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
                            )
                }
                ?: cm?.activeNetwork
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
        val need = hosts.filter { it.isNotBlank() && !out.containsKey(it.lowercase()) }
        if (need.isEmpty()) return
        if (need.size == 1) {
            val h = need[0]
            val ip = runCatching {
                InetAddress.getAllByName(h)
                    .firstOrNull { it.hostAddress?.contains(':') != true }?.hostAddress
            }.getOrNull()
            if (!ip.isNullOrBlank()) out[h.lowercase()] = ip
            return
        }
        // Параллельный DNS — на cold start 7 хостов подряд давали 1–3с.
        val pool = java.util.concurrent.Executors.newFixedThreadPool(need.size.coerceAtMost(6))
        try {
            val futures = need.map { h ->
                pool.submit<Pair<String, String?>> {
                    val ip = runCatching {
                        InetAddress.getAllByName(h)
                            .firstOrNull { it.hostAddress?.contains(':') != true }?.hostAddress
                    }.getOrNull()
                    h.lowercase() to ip
                }
            }
            for (f in futures) {
                val (h, ip) = runCatching {
                    f.get(2, java.util.concurrent.TimeUnit.SECONDS)
                }.getOrNull() ?: continue
                if (!ip.isNullOrBlank()) out[h] = ip
            }
        } finally {
            pool.shutdownNow()
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
        // После kill app RAM пуст — поднять CONN_FILE с диска (тот же room, TTL).
        val disk = File(context.filesDir, "telemost-conn.json")
        if (disk.isFile) {
            val body = runCatching { disk.readText() }.getOrNull().orEmpty()
            val obj = runCatching { JSONObject(body) }.getOrNull()
            val diskRoom = obj?.optString("room_id").orEmpty()
            val until = disk.lastModified() + OlcrtcRecoveryPolicy.PREFETCH_TTL_MS
            if (
                body.isNotBlank() &&
                OlcrtcRecoveryPolicy.shouldReusePrefetchCache(
                    OlcrtcRecoveryPolicy.PrefetchReuseInput(
                        cachedRoom = diskRoom.ifBlank { null },
                        requestRoom = room,
                        untilMs = until,
                        nowMs = System.currentTimeMillis(),
                        fileExists = true,
                    ),
                )
            ) {
                telemostPrefetchCache = PrefetchCache(room, disk, until)
                WdttTunnelManager.logUi("olcrtc_tm_auth", "Yandex auth disk hit", 1)
                runCatching {
                    val media = obj?.optJSONObject("client_configuration")
                        ?.optString("media_server_url").orEmpty()
                    hostFromUrl(media)?.let { resolveInto(staticHosts, it) }
                }
                resolveInto(staticHosts, "cloud-api.yandex.ru", "telemost.yandex.ru", "goloom.strm.yandex.net")
                return disk
            }
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
                        } else if (resp.code == 404 || body.contains("not found", ignoreCase = true)) {
                            lastFailHint =
                                "WB join 404: комната не найдена (мёртвая room) — смените канал"
                            wbPrefetchCache = null
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
                    } else if (resp.code == 404 || body.contains("not found", ignoreCase = true)) {
                        lastFailHint =
                            "WB token 404: комната не найдена (мёртвая room) — смените канал"
                        wbPrefetchCache = null
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
                // WB: без CONN_FILE — Go guest (короткий LiveKit token из OkHttp убивал peer).
                WdttTunnelManager.logUi(
                    "olcrtc_wb_prefetch",
                    "WB hosts only (без CONN_FILE — Go guest сам)",
                    1,
                )
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

    private fun waitForSocks(
        host: String,
        port: Int,
        timeoutMs: Long,
        proc: Process? = null,
        epoch: Int = startEpoch.get(),
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (epoch != startEpoch.get()) return false
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
