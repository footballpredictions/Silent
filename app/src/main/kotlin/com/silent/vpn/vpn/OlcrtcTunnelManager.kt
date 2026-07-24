package com.silent.vpn.vpn

import android.content.Context
import android.net.IpPrefix
import android.net.VpnService
import android.os.Build
import android.os.ParcelFileDescriptor
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

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
        val isBootstrap: Boolean = false,
        /** LTE DPI: HTTP CONNECT к Улью, дальше meet.egovm.ru */
        val httpsProxy: String = "",
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
    @Volatile private var lastFailHint: String = ""
    private val worker = Executors.newSingleThreadExecutor { r ->
        Thread(r, "olcrtc-start").apply { isDaemon = true }
    }

    fun stop() {
        _tunnelReady.value = false
        _running.value = false
        starting.set(false)
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
        DebugLog.i("Olcrtc", "session stopped")
        WdttTunnelManager.logUi("olcrtc_stop", "session stopped", 3)
    }

    /**
     * Быстрый старт: spawn процесса и сразу return.
     * tunnelReady / lastError обновляются в фоне.
     */
    fun start(context: Context, params: Params, vpnService: VpnService? = null): String? {
        if (!starting.compareAndSet(false, true)) return "olcrtc: already starting"
        _lastError.value = null
        _tunnelReady.value = false
        try {
            stopKeepStarting()
            lastFailHint = ""
            if (params.cryptoKey.length != 64 || params.room.isBlank()) {
                starting.set(false)
                return "olcrtc: нужны room и crypto_key из /api/vpn/olcrtc-config"
            }
            val olcrtcBin = ensureOlcrtcBinary(context)
                ?: run {
                    starting.set(false)
                    return "olcrtc: libolcrtc.so не найден в nativeLibraryDir (jniLibs)"
                }

            val dataDir = File(context.filesDir, "olcrtc-data").apply { mkdirs() }
            val yamlFile = File(context.filesDir, "olcrtc-client.yaml")
            val yaml = renderClientYaml(params)
                .replace(Regex("""(?m)^data: data$"""), "data: \"${dataDir.absolutePath}\"")
            yamlFile.writeText(yaml)

            WdttTunnelManager.logUi(
                "olcrtc_start",
                "start ${params.provider} room=${params.room.take(40)}…",
                1,
            )
            DebugLog.i("Olcrtc", "start provider=${params.provider} bin=$olcrtcBin")

            val libDir = context.applicationInfo.nativeLibraryDir
            if (params.httpsProxy.isNotBlank()) {
                WdttTunnelManager.logUi(
                    "olcrtc_proxy",
                    "HTTPS_PROXY=${params.httpsProxy.take(48)} (LTE DPI bypass)",
                    1,
                )
            }
            val proc = startOlcrtcProcess(context, olcrtcBin, yamlFile.absolutePath, dataDir, libDir, params.httpsProxy)
            olcrtcProc = proc
            _running.value = true
            pipeLogs(proc)
            watchExit(proc)

            worker.execute {
                try {
                    if (!waitForSocks(params.socksHost, params.socksPort, 90_000)) {
                        val exited = try {
                            proc.exitValue()
                        } catch (_: Exception) {
                            null
                        }
                        val msg = when {
                            exited != null && lastFailHint.isNotBlank() -> lastFailHint
                            exited != null ->
                                "olcrtc вышел code=$exited до SOCKS (бинарь/room/peer/Jitsi)"
                            else ->
                                "olcrtc SOCKS не поднялся на ${params.socksHost}:${params.socksPort}"
                        }
                        _lastError.value = msg
                        WdttTunnelManager.logUi("olcrtc_socks_fail", msg, 99, isError = true)
                        stop()
                        return@execute
                    }
                    WdttTunnelManager.logUi(
                        "olcrtc_socks",
                        "SOCKS listen ${params.socksHost}:${params.socksPort}",
                        1,
                    )
                    if (!waitForSocksDial(params.socksHost, params.socksPort, 60_000)) {
                        val msg = "olcrtc SOCKS слушает, но peer не отвечает (dial timeout)"
                        _lastError.value = msg
                        WdttTunnelManager.logUi("olcrtc_dial_fail", msg, 99, isError = true)
                        stop()
                        return@execute
                    }
                    WdttTunnelManager.logUi("olcrtc_dial", "SOCKS dial OK", 1)
                    if (vpnService != null) {
                        val tunErr = attachHevTun(context, params, vpnService)
                        if (tunErr != null) {
                            _lastError.value = tunErr
                            WdttTunnelManager.logUi("olcrtc_tun_fail", tunErr, 99, isError = true)
                            stop()
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
                } catch (e: Exception) {
                    val msg = e.message ?: "olcrtc background start failed"
                    _lastError.value = msg
                    WdttTunnelManager.logUi("olcrtc_bg_fail", msg, 99, isError = true)
                    DebugLog.e("Olcrtc", "bg start failed", e)
                    stop()
                } finally {
                    starting.set(false)
                }
            }
            return null
        } catch (e: Exception) {
            starting.set(false)
            val msg = e.message ?: "olcrtc start failed"
            _lastError.value = msg
            WdttTunnelManager.logUi("olcrtc_start_fail", msg, 99, isError = true)
            return msg
        }
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
                        if (Regex(
                                """\[ice\] TRACE|\[sctp\] TRACE|bufferedAmount|service-unavailable|extdisco|disco_1|\[xmpp|Failed to send packet|operation not permitted|Failed to ping without candidate|Failed to listen udp|fe80:|%dummy0""",
                                RegexOption.IGNORE_CASE,
                            ).containsMatchIn(l)
                        ) {
                            continue
                        }
                        DebugLog.i("Olcrtc", l.take(300))
                        if (
                            l.contains("failed to send handshake", ignoreCase = true) ||
                            l.contains("WebSocket dial", ignoreCase = true) ||
                            l.contains("xmpp dial", ignoreCase = true)
                        ) {
                            lastFailHint =
                                "Jitsi WebSocket недоступен (часто DPI на LTE). Wi‑Fi или другой host в админке."
                        } else if (l.contains("remote not ready", ignoreCase = true)) {
                            lastFailHint =
                                "peer srv не в комнате (проверьте olcrtc@android / не делите data/ с PC)"
                        }
                        if (n <= 25 ||
                            l.contains("error", ignoreCase = true) ||
                            l.contains("fail", ignoreCase = true) ||
                            l.contains("SOCKS", ignoreCase = true) ||
                            l.contains("Link connected", ignoreCase = true) ||
                            l.contains("joining", ignoreCase = true)
                        ) {
                            val isErr = l.contains("error", true) || l.contains("fail", true)
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

    private fun watchExit(proc: Process) {
        Thread({
            try {
                val code = proc.waitFor()
                WdttTunnelManager.logUi("olcrtc_exit", "olcrtc process exit code=$code", 99, isError = code != 0)
                if (_running.value && !_tunnelReady.value) {
                    _lastError.value = "olcrtc вышел code=$code"
                }
            } catch (_: Exception) {
            }
        }, "olcrtc-exit").apply { isDaemon = true }.start()
    }

    /** TUN → SOCKS через hev-socks5-tunnel (JNI). App исключаем — olcrtc/Jitsi вне туннеля. */
    private fun attachHevTun(context: Context, params: Params, vpnService: VpnService): String? {
        if (!HevSocksTunnel.ensureLoaded()) {
            return "libhev-socks5-tunnel.so не загружен"
        }
        val conf = File(context.filesDir, "hev-olcrtc.yml")
        conf.writeText(
            """
            tunnel:
              mtu: 1280
              ipv4: 10.8.0.2
            socks5:
              port: ${params.socksPort}
              address: ${params.socksHost}
              udp: 'tcp'
            misc:
              log-level: warn
            """.trimIndent() + "\n",
        )
        return try {
            val builder = vpnService.Builder()
                .setSession("Silent olcrtc")
                .setMtu(1280)
                .addAddress("10.8.0.2", 32)
                .addRoute("0.0.0.0", 0)
                .addDnsServer("8.8.8.8")
                .addDnsServer("1.1.1.1")
            // hev/SOCKS TCP-only: UDP DNS через туннель мёртв (Telegram по IP ок, сайты нет).
            // API 33+: DNS напрямую в сеть (сайты резолвятся). App всё равно excluded для ICE.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                runCatching {
                    builder.excludeRoute(IpPrefix(InetAddress.getByName("8.8.8.8"), 32))
                    builder.excludeRoute(IpPrefix(InetAddress.getByName("1.1.1.1"), 32))
                    builder.excludeRoute(IpPrefix(InetAddress.getByName("8.8.4.4"), 32))
                }
            }
            runCatching { builder.addDisallowedApplication(context.packageName) }
            val pfd = builder.establish()
                ?: return "VpnService.Builder.establish() вернул null"
            tunFd = pfd
            val ok = HevSocksTunnel.TProxyStartService(conf.absolutePath, pfd.fd)
            if (!ok) {
                runCatching { pfd.close() }
                tunFd = null
                return "hev TProxyStartService failed"
            }
            WdttTunnelManager.logUi("olcrtc_tun", "hev TUN ok fd=${pfd.fd} dns=direct-exclude", 1)
            null
        } catch (e: Exception) {
            "hev TUN: ${e.message}"
        }
    }

    /** SOCKS5 CONNECT по домену — peer + DNS через туннель (как на PC). */
    private fun waitForSocksDial(host: String, port: Int, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        val domain = "www.gstatic.com"
        val domainBytes = domain.toByteArray(Charsets.US_ASCII)
        while (System.currentTimeMillis() < deadline) {
            try {
                Socket().use { s ->
                    s.soTimeout = 3500
                    s.connect(InetSocketAddress(host, port), 800)
                    s.getOutputStream().write(byteArrayOf(0x05, 0x01, 0x00))
                    val greet = ByteArray(2)
                    if (s.getInputStream().read(greet) < 2 || greet[0] != 0x05.toByte() || greet[1] != 0x00.toByte()) {
                        Thread.sleep(500)
                        return@use
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
                    s.getOutputStream().write(req)
                    val resp = ByteArray(2)
                    if (s.getInputStream().read(resp) >= 2 && resp[1] == 0x00.toByte()) {
                        return true
                    }
                }
            } catch (_: Exception) {
            }
            Thread.sleep(500)
        }
        return false
    }

    fun startFromConfigJson(context: Context, json: String, vpnService: VpnService? = null): String? {
        val obj = JSONObject(json)
        val svc = vpnService ?: (context as? VpnService)
        return start(
            context,
            Params(
                provider = obj.optString("olcrtc_provider", "jitsi"),
                room = obj.optString("olcrtc_room"),
                cryptoKey = obj.optString("olcrtc_crypto_key"),
                transport = obj.optString("olcrtc_transport", "datachannel"),
                socksHost = obj.optString("olcrtc_socks_host", "127.0.0.1"),
                socksPort = obj.optInt("olcrtc_socks_port", 8808),
                isBootstrap = obj.optBoolean("is_bootstrap", false),
                httpsProxy = obj.optString("olcrtc_https_proxy", ""),
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

    private fun startOlcrtcProcess(
        context: Context,
        primaryBin: String,
        yamlPath: String,
        dataDir: File,
        libDir: String,
        httpsProxy: String = "",
    ): Process {
        val cmd = listOf(primaryBin, yamlPath)
        try {
            WdttTunnelManager.logUi("olcrtc_exec", "exec native/${File(primaryBin).name}", 2)
            return buildOlcrtcProcess(cmd, dataDir, libDir, httpsProxy).start()
        } catch (e: java.io.IOException) {
            // Только TV: codeCache (на телефонах codeCache тоже noexec → бессмысленно).
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
            return buildOlcrtcProcess(listOf(dest.absolutePath, yamlPath), dataDir, libDir, httpsProxy).start()
        }
    }

    private fun buildOlcrtcProcess(
        cmd: List<String>,
        dataDir: File,
        libDir: String,
        httpsProxy: String = "",
    ): ProcessBuilder =
        ProcessBuilder(cmd).apply {
            directory(dataDir)
            redirectErrorStream(true)
            environment()["LD_LIBRARY_PATH"] = libDir
            val proxy = httpsProxy.trim()
            if (proxy.isNotEmpty()) {
                environment()["HTTPS_PROXY"] = proxy
                environment()["HTTP_PROXY"] = proxy
                environment()["https_proxy"] = proxy
                environment()["http_proxy"] = proxy
                // Go net/http
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

    private fun waitForSocks(host: String, port: Int, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
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

    private fun renderClientYaml(p: Params): String = """
        mode: cnc
        auth:
          provider: ${p.provider}
        room:
          id: "${p.room}"
        crypto:
          key: "${p.cryptoKey}"
        net:
          transport: ${p.transport}
          dns: "8.8.8.8:53"
        socks:
          host: "${p.socksHost}"
          port: ${p.socksPort}
        data: data
    """.trimIndent() + "\n"
}
