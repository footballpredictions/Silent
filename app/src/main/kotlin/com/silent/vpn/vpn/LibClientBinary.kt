package com.silent.vpn.vpn

import android.content.Context
import com.silent.vpn.util.DebugLog
import com.silent.vpn.util.DevicePlatform
import com.silent.vpn.vpn.WdttTunnelManager
import java.io.File
import java.io.IOException

/**
 * Путь к libclient. По умолчанию — [nativeLibraryDir].
 * На TV при ошибке exec — копия в codeCache (SELinux на части приставок).
 */
object LibClientBinary {

    fun resolvePrimary(context: Context): String {
        val source = File(context.applicationContext.applicationInfo.nativeLibraryDir, "libclient.so")
        require(source.exists()) {
            "libclient.so не найден (ABI ${DevicePlatform.primaryAbi()})"
        }
        return source.absolutePath
    }

    fun resolveCodeCacheFallback(context: Context): String {
        val appContext = context.applicationContext
        val source = File(appContext.applicationInfo.nativeLibraryDir, "libclient.so")
        val abi = DevicePlatform.primaryAbi()
        val dest = File(appContext.codeCacheDir, "wdtt-libclient-$abi.so")
        if (!dest.exists() || dest.length() != source.length() || dest.lastModified() < source.lastModified()) {
            source.copyTo(dest, overwrite = true)
            dest.setReadable(true, false)
            dest.setWritable(true, false)
            dest.setExecutable(true, false)
            DebugLog.i("LibClientBinary", "fallback: ${dest.absolutePath}")
        }
        return dest.absolutePath
    }

    fun startLibclientProcess(
        context: Context,
        cmd: List<String>,
        libDir: String,
        filesDir: File,
    ): Process {
        val primary = resolvePrimary(context)
        val commands = cmd.toMutableList()
        commands[0] = primary
        try {
            return buildProcess(commands, libDir, filesDir).start()
        } catch (e: IOException) {
            if (!DevicePlatform.isTv(context)) throw e
            val fallback = resolveCodeCacheFallback(context)
            commands[0] = fallback
            DebugLog.w("LibClientBinary", "exec primary failed (${e.message}), retry $fallback")
            WdttTunnelManager.traceApp("libclient_fallback", "primary exec failed, retry codeCache")
            return buildProcess(commands, libDir, filesDir).start()
        }
    }

    private fun buildProcess(cmd: List<String>, libDir: String, filesDir: File): ProcessBuilder =
        ProcessBuilder(cmd).apply {
            directory(filesDir)
            redirectErrorStream(true)
            environment()["LD_LIBRARY_PATH"] = libDir
        }
}
