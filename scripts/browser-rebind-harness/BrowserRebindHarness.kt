package recovery.harness

import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import com.silent.vpn.vpn.AppTunnelPolicy
import com.silent.vpn.vpn.BrowserScopedTunnel
import com.wireguard.config.Config
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.lang.reflect.InvocationTargetException
import sun.misc.Unsafe

/** Executes the shipped BrowserScopedTunnel start/stop code, without a live Android VPN. */
private class ProbeContext : ContextWrapper(null) {
    lateinit var probeApplicationInfo: ApplicationInfo
    override fun getApplicationInfo(): ApplicationInfo = probeApplicationInfo
}

private class LiveNativeProcess : Process() {
    var destroyed = false
    override fun getInputStream() = ByteArrayInputStream(byteArrayOf())
    override fun getErrorStream() = ByteArrayInputStream(byteArrayOf())
    override fun getOutputStream() = ByteArrayOutputStream()
    override fun waitFor(): Int = if (destroyed) 0 else error("Unexpected blocking process wait")
    override fun exitValue(): Int {
        if (!destroyed) throw IllegalThreadStateException("Native transport is still alive")
        return 0
    }
    override fun destroy() { destroyed = true }
}

fun main() {
    val unsafe = Unsafe::class.java.getDeclaredField("theUnsafe").apply { isAccessible = true }.get(null) as Unsafe
    // The SDK jar throws from Android constructors, so allocate only this narrow Context double.
    val context = unsafe.allocateInstance(ProbeContext::class.java) as ProbeContext
    context.probeApplicationInfo = (unsafe.allocateInstance(ApplicationInfo::class.java) as ApplicationInfo).apply {
        nativeLibraryDir = "./intentional-no-native-module-for-recovery-probe"
    }
    val config = unsafe.allocateInstance(Config::class.java) as Config
    val processField = BrowserScopedTunnel::class.java.getDeclaredField("process").apply { isAccessible = true }
    val keyField = BrowserScopedTunnel::class.java.getDeclaredField("key").apply { isAccessible = true }
    val start = BrowserScopedTunnel::class.java.declaredMethods.single { it.name == "start" }
    val supportsForce = start.parameterCount == 9
    fun startSamePolicy(force: Boolean) {
        val args = mutableListOf<Any>(context, config, AppTunnelPolicy(false, emptySet()), emptyList<String>(),
            emptyList<String>(), emptyList<String>(), false, "same-policy-and-wireguard-config")
        if (supportsForce) args += force
        start.invoke(BrowserScopedTunnel, *args.toTypedArray())
    }
    val native = LiveNativeProcess()
    processField.set(BrowserScopedTunnel, native)
    keyField.set(BrowserScopedTunnel, "same-policy-and-wireguard-config")
    try {
        startSamePolicy(false)
        check(!native.destroyed && BrowserScopedTunnel.isRunning()) {
            "Normal capabilities update restarted a healthy native transport"
        }
        println("PASS normal same-policy refresh preserves the native transport")
        var reinitializationEntered = false
        try {
            startSamePolicy(true)
        } catch (error: InvocationTargetException) {
            val cause = error.targetException
            check(cause is IllegalStateException && cause.message?.contains("Отсутствует модуль правил сайтов") == true) {
                "Unexpected recovery failure: $cause"
            }
            reinitializationEntered = true
        }
        check(native.destroyed && processField.get(BrowserScopedTunnel) == null && reinitializationEntered) {
            "Network recovery reused the stale native process for identical semanticKey instead of rebinding its sockets"
        }
        println("PASS forced same-policy recovery closes old native transport and enters reinitialization")
    } finally {
        BrowserScopedTunnel.stop()
    }
}
