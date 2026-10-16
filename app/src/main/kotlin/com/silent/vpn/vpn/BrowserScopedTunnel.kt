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
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.security.MessageDigest
import com.silent.vpn.policy.TunnelDataWatch
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

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
    private var deviceFingerprint: String? = null
    private var targetRevision = 0L
    private class TargetAck(val revision: Long) {
        val done = CountDownLatch(1)
        var applied = false
    }
    @Volatile private var targetAck: TargetAck? = null

    private fun alive(value: Process?): Boolean = value != null &&
        runCatching { value.exitValue(); false }.getOrDefault(true)

    @Synchronized fun isRunning(): Boolean = alive(process)

    /** Revision-only update: preserve the native WG device, TUN and application sockets. */
    @Synchronized internal fun applyRussianPolicy(context: Context): Boolean {
        if (!alive(process)) return false
        val policy = com.silent.vpn.data.RussianServices.config(context)
        val ack = TargetAck(++targetRevision)
        targetAck = ack
        return try {
            val update = JSONObject().put("revision", ack.revision).put("russian", policy)
            checkNotNull(process).outputStream.apply { write((update.toString() + "\n").toByteArray()); flush() }
            check(ack.done.await(2_500, TimeUnit.MILLISECONDS) && ack.applied)
            key = null // A later full reapply must still reconcile its semantic key.
            com.silent.vpn.data.RussianServices.applied(context, policy)
            true
        } catch (e: Exception) {
            DebugLog.w("BrowserRouting", "policy update not acknowledged: ${e.message}")
            false
        } finally { if (targetAck === ack) targetAck = null }
    }

    internal class PhysicalRecovery internal constructor(internal val native: Process, internal val epoch: Long, internal val dns: List<String>)
    private val physicalEpoch = AtomicLong()

    private fun physicalDns(context: Context): List<String> = runCatching {
        val network = VpnNetworkHelper.findUnderlyingNetwork(context) ?: return@runCatching emptyList()
        context.getSystemService(ConnectivityManager::class.java).getLinkProperties(network)?.dnsServers
            ?.mapNotNull { it.hostAddress }?.take(4).orEmpty()
    }.getOrDefault(emptyList())

    internal fun newPhysicalRecovery(context: Context? = null): PhysicalRecovery? = process?.takeIf { alive(it) }?.let {
        PhysicalRecovery(it, physicalEpoch.incrementAndGet(), context?.let(::physicalDns).orEmpty())
    }

    /** Close sockets from the lost physical network; retain policy, WG and TUN. */
    internal fun recoverPhysicalNetwork(): Boolean = newPhysicalRecovery()?.let { recoverPhysicalNetwork(it) } ?: true

    @Synchronized internal fun recoverPhysicalNetwork(recovery: PhysicalRecovery): Boolean {
        // A late callback/retry must not reset a replacement process or newer path.
        if (process !== recovery.native || !alive(process) || recovery.epoch != physicalEpoch.get()) return true
        return runCatching {
            val ack = TargetAck(++targetRevision)
            targetAck = ack
            try {
                val update = JSONObject().put("revision", ack.revision).put("network_epoch", recovery.epoch)
                    .put("physical_dns", JSONArray(recovery.dns))
                checkNotNull(process).outputStream.apply { write((update.toString() + "\n").toByteArray()); flush() }
                check(ack.done.await(2_500, TimeUnit.MILLISECONDS) && ack.applied)
                DebugLog.i("BrowserRouting", "physical sockets refreshed; WG/TUN preserved")
            } finally { if (targetAck === ack) targetAck = null }
        }.onFailure { DebugLog.w("BrowserRouting", "physical recovery: ${it.message}") }.isSuccess
    }

    /** Local counters only: no radio traffic, DNS, timer, or additional WireGuard peer. */
    internal fun pathHealth(): TunnelDataWatch.Sample? = localRequest("/_silent/health", 1_000) { connection ->
        if (connection.responseCode != 200) return@localRequest null
        val json = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
        TunnelDataWatch.Sample(json.getLong("sent"), json.getLong("received"))
    }

    internal fun probePath(): Boolean = localRequest("/api/updates/check?platform=android", 5_000) {
        it.responseCode
        it.getHeaderField("X-Silent-Upstream") == "1"
    } ?: false

    private fun <T> localRequest(path: String, timeout: Int, read: (HttpURLConnection) -> T): T? {
        val connection = URL(OTA_BASE_URL + path).openConnection(Proxy.NO_PROXY) as HttpURLConnection
        return try {
            connection.connectTimeout = 1_000
            connection.readTimeout = timeout
            connection.useCaches = false
            connection.instanceFollowRedirects = false
            read(connection)
        } catch (_: Exception) { null } finally { connection.disconnect() }
    }

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
        russian: JSONObject = JSONObject(),
    ) {
        if (key == semanticKey && isRunning()) return
        val browsers = if (whitelist || targets.isNotEmpty() || domains.isNotEmpty()) browserUids(context) else emptySet()
        val shape = JSONObject().apply {
            put("russian_enabled", russian.optBoolean("enabled", false))
            put("wg", config.toWgUserspaceString())
            put("addresses", config.`interface`.addresses.joinToString(","))
            put("dns", config.`interface`.dnsServers.joinToString(","))
            put("mtu", config.`interface`.mtu.orElse(1200))
            put("apps", JSONArray(appPolicy.packages.sorted()))
            put("excludes", JSONArray(transportExcludes.sorted()))
            put("domains", JSONArray(domains.sorted()))
            put("whitelist", whitelist)
            put("browsers", JSONArray(browsers.sorted()))
        }.toString()
        val fingerprint = MessageDigest.getInstance("SHA-256").digest(shape.toByteArray())
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        if (deviceFingerprint == fingerprint && isRunning()) {
            val ack = TargetAck(++targetRevision)
            targetAck = ack
            try {
                val update = JSONObject().put("revision", ack.revision).put("targets", JSONArray(targets.toList()))
                    .put("russian", russian)
                checkNotNull(process).outputStream.apply { write((update.toString() + "\n").toByteArray()); flush() }
                check(ack.done.await(2_500, TimeUnit.MILLISECONDS) && ack.applied) { "Не подтверждено обновление адресов обхода" }
                key = semanticKey
                com.silent.vpn.data.RussianServices.applied(context, russian)
                DebugLog.i("BrowserRouting", "site addresses updated; WG/TUN preserved")
                return
            } finally { if (targetAck === ack) targetAck = null }
        }
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
                    put("russian", russian)
                    put("physical_dns", JSONArray(physicalDns(context)))
                    put("socket", socketName)
                    put("wireguard", config.toWgUserspaceString())
                    put("mtu", config.`interface`.mtu.orElse(1200))
                    put("ota_port", OTA_PORT)
                    put("ota_address", config.`interface`.addresses.first().address.hostAddress)
                    put("whitelist", whitelist)
                    put("debug", BuildConfig.DEBUG)
                    put("targets", JSONArray(targets.toList()))
                    put("domains", JSONArray(domains.toList()))
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
                        else if (line.startsWith("POLICY_READY:")) {
                            targetAck?.takeIf { it.revision == line.substringAfter(':').toLongOrNull() }?.let {
                                it.applied = true
                                it.done.countDown()
                            }
                        }
                        else if (line.startsWith("FLOW ")) DebugLog.d("BrowserRouting", line)
                        else DebugLog.w("BrowserRouting", line.take(180))
                    }
                } finally {
                    ready.countDown()
                    if (process === native) targetAck?.done?.countDown()
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
            deviceFingerprint = fingerprint
            com.silent.vpn.data.RussianServices.applied(context, russian)
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
        com.silent.vpn.data.RussianServices.tunnelStopped()
        key = null
        deviceFingerprint = null
        targetAck?.done?.countDown()
        targetAck = null
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
