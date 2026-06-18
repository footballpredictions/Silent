package com.silent.vpn.vpn

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.util.Log
import com.silent.vpn.data.SilentRepository
import com.silent.vpn.service.SilentVpnService
import com.silent.vpn.util.DebugLog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URL
import java.nio.charset.Charset
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Локальный HTTP-прокси 127.0.0.1 → 10.66.66.1:8000 через VPN.
 * App excluded из WG — libclient/TURN напрямую; API на localhost, upstream через bind к VPN Network.
 * libclient.so пересобирать не нужно.
 */
object TunnelApiProxy {
    private const val TAG = "TunnelApiProxy"
    private const val LISTEN_HOST = "127.0.0.1"
    const val LISTEN_PORT = 18765
    private const val UPSTREAM_HOST = SilentRepository.WG_TUNNEL_GATEWAY
    private const val UPSTREAM_PORT = 8000
    private const val MAX_HEADER_BYTES = 64 * 1024
    private const val MAX_BODY_BUFFER = 4 * 1024 * 1024

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val startMutex = Mutex()
    private val upstreamLock = Any()
    private val active = AtomicBoolean(false)

    @Volatile private var appContext: Context? = null
    private var serverSocket: ServerSocket? = null
    private var acceptJob: Job? = null

    fun baseUrl(): String = "http://$LISTEN_HOST:$LISTEN_PORT"

    fun isActive(): Boolean = active.get()

    suspend fun start(context: Context) {
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) return
        if (WdttTunnelManager.isBootstrapMode()) return
        if (!WdttTunnelManager.running.value || !WdttTunnelManager.tunnelReady.value) return
        startMutex.withLock {
            if (active.get()) return
            val ctx = context.applicationContext
            appContext = ctx
            val socket = ServerSocket(LISTEN_PORT, 16, InetAddress.getByName(LISTEN_HOST))
            serverSocket = socket
            active.set(true)
            acceptJob = scope.launch { acceptLoop(socket) }
            DebugLog.i(TAG, "listening ${baseUrl()} → $UPSTREAM_HOST:$UPSTREAM_PORT")
            scope.launch {
                val ok = verifyUpstream(ctx)
                if (ok) {
                    DebugLog.i(TAG, "upstream VPN route OK")
                } else {
                    Log.w(TAG, "upstream check failed — proxy listens, requests use bind retry")
                }
            }
        }
    }

    fun startAsync(context: Context) {
        scope.launch { start(context) }
    }

    suspend fun ensureStarted(context: Context, timeoutMs: Long = 20_000L): Boolean {
        if (isActive()) return true
        if (!SilentRepository.APP_EXCLUDED_FROM_VPN) return false
        if (WdttTunnelManager.isBootstrapMode()) return false
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            start(context)
            if (isActive()) return true
            delay(350)
        }
        return isActive()
    }

    fun stop() {
        scope.launch { stopAndAwait() }
    }

    suspend fun stopAndAwait() = withContext(Dispatchers.IO) {
        startMutex.withLock {
            if (!active.getAndSet(false)) return@withLock
            acceptJob?.cancel()
            acceptJob = null
            runCatching { serverSocket?.close() }
            serverSocket = null
            appContext = null
            DebugLog.i(TAG, "stopped")
        }
    }

    suspend fun verifyUpstream(context: Context): Boolean = withContext(Dispatchers.IO) {
        val paths = listOf("/health", "/api/health", "/api/vpn/theme")
        for (path in paths) {
            val ok = runCatching {
            withVpnBound(context.applicationContext) { network ->
                    probeGet(network, path)
                }
            }.getOrDefault(false)
            if (ok) {
                DebugLog.i(TAG, "verify OK: $path")
                return@withContext true
            }
        }
        false
    }

    private fun probeGet(network: Network, path: String): Boolean {
        val conn = openDirectConnection(network, "GET", path, emptyMap(), null)
        try {
            conn.connect()
            return conn.responseCode in 200..499
        } finally {
            conn.disconnect()
        }
    }

    private suspend fun acceptLoop(socket: ServerSocket) {
        while (active.get()) {
            val client = runCatching { socket.accept() }.getOrElse { e ->
                if (active.get()) Log.w(TAG, "accept: ${e.message}")
                null
            } ?: break
            scope.launch {
                runCatching { handleClient(client) }
                    .onFailure { e -> Log.w(TAG, "client: ${e.message}") }
                runCatching { client.close() }
            }
        }
    }

    private fun handleClient(client: Socket) {
        client.soTimeout = 120_000
        val input = BufferedInputStream(client.getInputStream())
        val output = BufferedOutputStream(client.getOutputStream())
        val headerBytes = readHeaders(input) ?: run {
            writeError(output, 400, "Bad Request")
            return
        }
        val headerText = headerBytes.toString(Charset.forName("ISO-8859-1"))
        val lines = headerText.split("\r\n")
        if (lines.isEmpty()) {
            writeError(output, 400, "Bad Request")
            return
        }
        val requestLine = lines[0].split(" ")
        if (requestLine.size < 2) {
            writeError(output, 400, "Bad Request")
            return
        }
        val method = requestLine[0].uppercase(Locale.US)
        val target = requestLine[1]
        if (method !in setOf("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")) {
            writeError(output, 405, "Method Not Allowed")
            return
        }
        val path = target.substringBefore('?')
        val query = target.substringAfter('?', missingDelimiterValue = "")
        val upstreamPath = if (query.isEmpty()) path else "$path?$query"

        val headers = parseHeaders(lines.drop(1))
        val contentLength = headers["content-length"]?.toIntOrNull() ?: 0
        val body = if (contentLength > 0) {
            if (contentLength > MAX_BODY_BUFFER) {
                writeError(output, 413, "Payload Too Large")
                return
            }
            readFully(input, contentLength)
        } else {
            null
        }

        val ctx = appContext ?: run {
            writeError(output, 503, "Proxy not ready")
            return
        }

        val forwardHeaders = headers.filterKeys { !hopByHopHeader(it) }
        val conn = runCatching {
            withVpnBound(ctx) { network ->
                openDirectConnection(network, method, upstreamPath, forwardHeaders, body)
            }
        }.getOrElse { e ->
            Log.w(TAG, "upstream open: ${e.message}")
            writeError(output, 502, "VPN upstream failed")
            return
        }

        try {
            conn.connect()
            val status = conn.responseCode
            val responseHeaders = conn.headerFields
            writeStatusLine(output, status, conn.responseMessage ?: "OK")
            responseHeaders.forEach { (key, values) ->
                if (key == null || hopByHopHeader(key)) return@forEach
                values.forEach { value ->
                    output.write("$key: $value\r\n".toByteArray())
                }
            }
            output.write("\r\n".toByteArray())
            val stream = if (status >= 400) conn.errorStream ?: conn.inputStream else conn.inputStream
            stream?.copyTo(output)
            output.flush()
        } catch (e: Exception) {
            Log.w(TAG, "upstream forward: ${e.message}")
            writeError(output, 502, "Upstream error")
        } finally {
            conn.disconnect()
        }
    }

    /**
     * Excluded app: bindProcessToNetwork или Network.openConnection для upstream.
     */
    private fun <T> withVpnBound(context: Context, block: (Network) -> T): T {
        val network = VpnNetworkHelper.getSilentVpnNetwork(context)
            ?: throw IllegalStateException("VPN network not found")
        synchronized(upstreamLock) {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val previous = cm.boundNetworkForProcess
            if (cm.bindProcessToNetwork(network)) {
                try {
                    return block(network)
                } finally {
                    cm.bindProcessToNetwork(previous)
                }
            }
            Log.w(TAG, "bindProcessToNetwork failed — Network.openConnection")
            return block(network)
        }
    }

    private fun openDirectConnection(
        network: Network,
        method: String,
        path: String,
        headers: Map<String, String>,
        body: ByteArray?,
    ): HttpURLConnection {
        val normalizedPath = if (path.startsWith("/")) path else "/$path"
        val url = URL("http://$UPSTREAM_HOST:$UPSTREAM_PORT$normalizedPath")
        val conn = network.openConnection(url) as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 15_000
        conn.readTimeout = when {
            normalizedPath.contains("download", ignoreCase = true) -> 600_000
            else -> 120_000
        }
        conn.doInput = true
        if (body != null) {
            conn.doOutput = true
            conn.setFixedLengthStreamingMode(body.size)
        }
        headers.forEach { (k, v) ->
            if (!hopByHopHeader(k)) conn.setRequestProperty(k, v)
        }
        if (body != null) {
            conn.outputStream.use { it.write(body) }
        }
        return conn
    }

    private fun hopByHopHeader(name: String): Boolean {
        val n = name.lowercase(Locale.US)
        return n in setOf(
            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
        )
    }

    private fun parseHeaders(lines: List<String>): Map<String, String> {
        val out = linkedMapOf<String, String>()
        for (line in lines) {
            if (line.isBlank()) break
            val idx = line.indexOf(':')
            if (idx <= 0) continue
            val name = line.substring(0, idx).trim()
            val value = line.substring(idx + 1).trim()
            out[name.lowercase(Locale.US)] = value
        }
        return out
    }

    private fun readHeaders(input: InputStream): ByteArray? {
        val buf = ByteArrayOutputStream()
        var state = 0
        var prev = 0
        while (buf.size() < MAX_HEADER_BYTES) {
            val b = input.read()
            if (b == -1) break
            buf.write(b)
            when {
                state == 0 && prev == '\r'.code && b == '\n'.code -> state = 1
                state == 1 && prev == '\r'.code && b == '\n'.code -> return buf.toByteArray()
                else -> if (b != '\r'.code) state = 0
            }
            prev = b
        }
        return null
    }

    private fun readFully(input: InputStream, length: Int): ByteArray {
        val buf = ByteArray(length)
        var off = 0
        while (off < length) {
            val n = input.read(buf, off, length - off)
            if (n <= 0) break
            off += n
        }
        return if (off == length) buf else buf.copyOf(off)
    }

    private fun writeStatusLine(output: OutputStream, code: Int, message: String) {
        output.write("HTTP/1.1 $code $message\r\n".toByteArray())
    }

    private fun writeError(output: OutputStream, code: Int, message: String) {
        val body = message.toByteArray()
        writeStatusLine(output, code, message)
        output.write("Content-Length: ${body.size}\r\n".toByteArray())
        output.write("Connection: close\r\n\r\n".toByteArray())
        output.write(body)
        output.flush()
    }
}
