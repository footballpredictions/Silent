package com.silent.vpn.vpn

import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.IpPrefix
import android.net.LocalServerSocket
import android.net.LocalSocket
import android.os.Build
import android.os.ParcelFileDescriptor
import com.silent.vpn.service.BrowserScopedVpnService
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.BuildConfig
import com.silent.vpn.util.DebugLog
import com.wireguard.config.Config
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.InetSocketAddress
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Application exclusions remain Android UID exclusions. The native TUN reader
 * asks Android for each flow's owner; only browser UIDs use the site policy.
 * Unknown owners retain the VPN. No global site routes or HTTP-proxy settings.
 */
object BrowserScopedTunnel {
    const val OTA_PORT = 18766
    const val OTA_BASE_URL = "http://127.0.0.1:$OTA_PORT"
    @Volatile private var process: Process? = null
    private var tun: ParcelFileDescriptor? = null
    private var server: LocalServerSocket? = null
    private var control: LocalSocket? = null
    private var configuration: File? = null
    private var key: String? = null

    private fun alive(value: Process?): Boolean = value != null &&
        runCatching { value.exitValue(); false }.getOrDefault(true)

    @Synchronized fun isRunning(): Boolean = alive(process)

    fun browserUids(context: Context): Set<Int> {
        val pm = context.packageManager
        val intents = listOf(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_APP_BROWSER),
            Intent(Intent.ACTION_VIEW, android.net.Uri.parse("https://example.com/"))
                .addCategory(Intent.CATEGORY_BROWSABLE),
        )
        return intents.flatMap { pm.queryIntentActivities(it, 0) }
            .mapNotNull { it.activityInfo?.applicationInfo?.uid }
            .filter { it >= 10000 }.toSet()
    }

    @Synchronized fun start(
        context: Context,
        config: Config,
        appPolicy: AppTunnelPolicy,
        transportExcludes: Collection<String>,
        targets: Collection<String>,
        domains: Collection<String>,
        whitelist: Boolean,
        semanticKey: String,
    ) {
        if (key == semanticKey && isRunning()) return
        stop()
        val binary = File(context.applicationInfo.nativeLibraryDir, "libsite-router.so")
        check(binary.canExecute()) { "Отсутствует модуль правил сайтов для этой архитектуры" }
        context.startService(Intent(context, BrowserScopedVpnService::class.java))
        repeat(40) {
            if (BrowserScopedVpnService.instance == null) Thread.sleep(50)
        }
        val service = checkNotNull(BrowserScopedVpnService.instance) { "Не запущен VPN сайтов" }
        try {
            val builder = service.Builder().setSession("Silent VPN")
                .setMtu(config.`interface`.mtu.orElse(1200)).setBlocking(true)
            for (address in config.`interface`.addresses) {
                builder.addAddress(address.address, address.mask)
            }
            for (dns in config.`interface`.dnsServers) builder.addDnsServer(dns)
            for (pkg in appPolicy.packages) builder.addDisallowedApplication(pkg)
            val routes = if (Build.VERSION.SDK_INT >= 33) "0.0.0.0/0"
                else AllowedIpsHelper.generateExclusionAllowedIPs(transportExcludes)
            for (cidr in routes.split(',').map { it.trim() }.filter { it.isNotEmpty() }) {
                val parts = cidr.split('/')
                builder.addRoute(parts[0], parts[1].toInt())
            }
            if (Build.VERSION.SDK_INT >= 33) {
                for (raw in transportExcludes) {
                    val cidr = if ('/' in raw) raw else "$raw/32"
                    val parts = cidr.split('/')
                    runCatching { builder.excludeRoute(IpPrefix(java.net.InetAddress.getByName(parts[0]), parts[1].toInt())) }
                }
            }
            if (Build.VERSION.SDK_INT >= 29) builder.setMetered(false)
            tun = checkNotNull(builder.establish()) { "VPN-разрешение отозвано" }
            val socketName = "silent-browser-${android.os.Process.myPid()}"
            server = LocalServerSocket(socketName)
            // Configuration contains a WG key: app-private file, removed on stop.
            configuration = File(context.noBackupFilesDir, "browser-routing-runtime.json").apply {
                writeText(JSONObject().apply {
                    put("socket", socketName)
                    put("wireguard", config.toWgUserspaceString())
                    put("mtu", config.`interface`.mtu.orElse(1200))
                    put("ota_port", OTA_PORT)
                    put("ota_address", config.`interface`.addresses.first().address.hostAddress)
                    put("whitelist", whitelist)
                    put("debug", BuildConfig.DEBUG)
                    put("targets", JSONArray(targets.toList()))
                    put("domains", JSONArray(domains.toList()))
                    val browsers = if (whitelist || targets.isNotEmpty() || domains.isNotEmpty()) browserUids(context) else emptySet()
                    put("browsers", JSONArray(browsers.toList()))
                }.toString())
            }
            val listener = server!!
            val fd = tun!!.fileDescriptor
            Thread({
                runCatching {
                    var socket: LocalSocket
                    while (true) {
                        val candidate = listener.accept()
                        if (candidate.peerCredentials.uid == context.applicationInfo.uid) {
                            socket = candidate
                            break
                        }
                        candidate.close()
                    }
                    if (server !== listener) { socket.close(); return@runCatching }
                    control = socket
                    socket.setFileDescriptorsForSend(arrayOf(fd))
                    socket.outputStream.write(1)
                    socket.setFileDescriptorsForSend(null)
                    val reader = socket.inputStream.bufferedReader()
                    val writer = socket.outputStream.bufferedWriter()
                    val cm = context.getSystemService(ConnectivityManager::class.java)
                    while (true) {
                        val line = reader.readLine() ?: break
                        val uid = runCatching {
                            val request = JSONObject(line)
                            val local = endpoint(request.getString("local"))
                            val remote = endpoint(request.getString("remote"))
                            if (Build.VERSION.SDK_INT >= 29) {
                                cm.getConnectionOwnerUid(request.getInt("protocol"), local, remote)
                            } else legacyOwner(request.getInt("protocol"), local, remote)
                        }.getOrDefault(-1)
                        writer.write("$uid\n")
                        writer.flush()
                    }
                }
            }, "browser-flow-owner").apply { isDaemon = true; start() }
            val ready = CountDownLatch(1)
            val readySeen = AtomicBoolean(false)
            val native = ProcessBuilder(binary.absolutePath, configuration!!.absolutePath)
                .redirectErrorStream(true).start()
            process = native
            Thread({
                try {
                    RouterProcessOutput.consume(native.inputStream) { line ->
                        if (line == "READY") { readySeen.set(true); ready.countDown() }
                        else if (line.startsWith("FLOW ")) DebugLog.d("BrowserRouting", line)
                        else DebugLog.w("BrowserRouting", line.take(180))
                    }
                } finally {
                    ready.countDown()
                    synchronized(this) {
                        // A retiring reader must never stop its replacement.
                        if (process === native) {
                            stop()
                            runCatching {
                                context.startService(Intent(context, SilentVpnService::class.java).apply {
                                    action = SilentVpnService.ACTION_EXTERNAL_REVOKED
                                })
                            }
                        }
                    }
                }
            }, "browser-router-status").apply { isDaemon = true; start() }
            check(ready.await(10, TimeUnit.SECONDS) && readySeen.get() && alive(native)) { "Не удалось запустить маршрутизацию браузеров" }
            configuration?.delete()
            configuration = null
            key = semanticKey
            DebugLog.i("BrowserRouting", "browser-only site rules active; other apps keep app policy")
        } catch (error: Throwable) {
            stop()
            throw error
        }
    }

    private fun endpoint(raw: String): InetSocketAddress =
        InetSocketAddress(raw.substringBeforeLast(':'), raw.substringAfterLast(':').toInt())

    private fun legacyOwner(protocol: Int, local: InetSocketAddress, remote: InetSocketAddress): Int {
        fun address(value: InetSocketAddress): String =
            value.address!!.address.reversed().joinToString("") { "%02X".format(it.toInt() and 255) } +
                ":%04X".format(value.port)
        val name = if (protocol == 6) "tcp" else "udp"
        val wanted = address(local)
        val destination = address(remote)
        return File("/proc/net/$name").useLines { lines ->
            lines.drop(1).map { it.trim().split(Regex("\\s+")) }
                .firstOrNull { it.size > 7 && it[1] == wanted &&
                    (it[2] == destination || protocol == 17 && it[2] == "00000000:0000") }
                ?.get(7)?.toIntOrNull() ?: -1
        }
    }

    @Synchronized fun stop() {
        key = null
        val oldProcess = process
        process = null
        runCatching { oldProcess?.outputStream?.close() }
        runCatching { control?.close() }
        runCatching { server?.close() }
        runCatching { tun?.close() }
        runCatching {
            oldProcess?.destroy()
            if (oldProcess != null && Build.VERSION.SDK_INT >= 26 &&
                !oldProcess.waitFor(250, TimeUnit.MILLISECONDS)) oldProcess.destroyForcibly()
        }
        control = null; server = null; tun = null
        configuration?.delete(); configuration = null
    }
}
