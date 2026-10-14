"""Run the real QS service/helper against small Android doubles, without Gradle.

Uses the Kotlin/coroutines artifacts already cached by this Android project.
The doubles represent Android's bound/unbound tile and deterministic main looper;
VPN state and service callbacks are the production Kotlin sources.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".gradle/caches/modules-2/files-2.1"
JAVA = Path(os.environ.get("JAVA_HOME", r"C:\Program Files\Android\Android Studio\jbr")) / "bin/java.exe"


def jar(group, artifact, version=None):
    candidates = sorted((CACHE / group / artifact).glob(f"{version or '*'}/**/*.jar"))
    if not candidates:
        raise RuntimeError(f"Missing cached artifact: {group}:{artifact}")
    return str(candidates[-1])


DOUBLES = {
    "content.kt": r'''
package android.content
open class Context {
    open val applicationContext: Context get() = this
    val started = mutableListOf<Intent>()
    var failActivityLaunch = false
    fun startService(intent: Intent): ComponentName { started += intent; return ComponentName(this, Any::class.java) }
    fun startActivity(intent: Intent) { check(!failActivityLaunch) { "activity launch rejected" } }
    fun getSystemService(name: String): Any = android.app.NotificationManager()
    fun getString(id: Int): String = id.toString()
    companion object { const val NOTIFICATION_SERVICE = "notification" }
}
class ComponentName(context: Context, klass: Class<*>)
class Intent(context: Context? = null, klass: Class<*>? = null) {
    var action: String? = null
    fun addFlags(flags: Int): Intent = this
    fun putExtra(key: String, value: String?): Intent = this
    fun getStringExtra(key: String): String? = null
    companion object {
        const val FLAG_ACTIVITY_NEW_TASK = 1; const val FLAG_ACTIVITY_REORDER_TO_FRONT = 2
        const val FLAG_ACTIVITY_SINGLE_TOP = 4; const val FLAG_ACTIVITY_CLEAR_TOP = 8
        const val FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS = 16
    }
}
''',
    "os.kt": r'''
package android.os
object Build {
    object VERSION { var SDK_INT = 35 }
    object VERSION_CODES { const val N = 24; const val O = 26; const val Q = 29; const val UPSIDE_DOWN_CAKE = 34 }
}
object SystemClock { var now = 100_000L; fun elapsedRealtime() = now }
class Looper { companion object { fun getMainLooper() = Looper() } }
class Handler(looper: Looper) {
    fun post(runnable: Runnable): Boolean { runnable.run(); return true }
    fun postDelayed(runnable: Runnable, delay: Long): Boolean {
        tasks += (SystemClock.now + delay) to runnable; return true
    }
    fun removeCallbacks(runnable: Runnable) { tasks.removeAll { it.second === runnable } }
    companion object {
        val tasks = mutableListOf<Pair<Long, Runnable>>()
        fun advanceBy(ms: Long) {
            SystemClock.now += ms
            while (tasks.any { it.first <= SystemClock.now }) {
                val next = tasks.filter { it.first <= SystemClock.now }.minBy { it.first }
                tasks.remove(next); next.second.run()
            }
        }
    }
}
''',
    "qs.kt": r'''
package android.service.quicksettings
import android.content.*
class Tile {
    var label = ""; var icon: Any? = null; var state = STATE_INACTIVE; var subtitle = ""
    var updates = 0
    fun updateTile() { updates++ }
    companion object { const val STATE_ACTIVE = 2; const val STATE_INACTIVE = 1; const val STATE_UNAVAILABLE = 0 }
}
open class TileService: Context() {
    val qsTile: Tile? = Tile()
    var isLocked = false
    var pendingUnlock: Runnable? = null
    var openedActivities = 0
    open fun onStartListening() {}; open fun onStopListening() {}; open fun onClick() {}
    open fun onDestroy() {}; open fun onTileAdded() {}
    fun unlockAndRun(runnable: Runnable) { pendingUnlock = runnable }
    fun startActivityAndCollapse(intent: Any) { openedActivities++ }
    companion object {
        var requests = 0
        fun requestListeningState(context: Context, component: ComponentName) { requests++ }
    }
}
''',
    "net.kt": r'''
package android.net
import android.content.Context
object VpnService { var permissionNeeded = false; fun prepare(context: Context): Any? = if (permissionNeeded) Any() else null }
''',
    "app.kt": r'''
package android.app
import android.content.*
class PendingIntent { companion object {
    const val FLAG_IMMUTABLE = 1; const val FLAG_UPDATE_CURRENT = 2
    fun getActivity(context: Context, code: Int, intent: Intent, flags: Int): PendingIntent = PendingIntent()
    fun getBroadcast(context: Context, code: Int, intent: Intent, flags: Int): PendingIntent = PendingIntent()
} }
class NotificationChannel(id: String, title: String, importance: Int)
class NotificationManager {
    fun createNotificationChannel(channel: NotificationChannel) {}
    fun notify(id: Int, notification: Any) {}
    fun cancel(id: Int) {}
    companion object { const val IMPORTANCE_HIGH = 1 }
}
''',
    "icon.kt": r'''
package android.graphics.drawable
class Icon
''',
    "log.kt": r'''
package android.util
object Log {
    fun w(tag: String, msg: String, e: Throwable? = null) = 0; fun e(tag: String, msg: String, e: Throwable? = null) = 0
    fun d(tag: String, msg: String) = 0
}
''',
    "toast.kt": r'''
package android.widget
import android.content.Context
class Toast { fun show() {}; companion object {
    const val LENGTH_LONG = 1; const val LENGTH_SHORT = 0
    fun makeText(context: Context, text: String, duration: Int) = Toast()
} }
''',
    "annotations.kt": r'''
package androidx.annotation
annotation class RequiresApi(val value: Int)
''',
    "compat.kt": r'''
package androidx.core.content
import android.content.*
object ContextCompat { fun startForegroundService(context: Context, intent: Intent) = context.startService(intent) }
''',
    "brand.kt": r'''
package com.silent.vpn.ui
import android.content.Context
object BrandMarkIcons { fun tileIcon(context: Context): Any = Any() }
''',
    "silent.kt": r'''
package com.silent.vpn
import android.content.*
class SilentApp: Context() { fun getBackend(context: Context) {} }
object MainActivity { var isForeground = false; fun openIntent(context: Context) = Intent() }
object R { object string {
    const val app_name = 1; const val tile_subtitle_captcha = 2; const val tile_subtitle_connected = 3
    const val tile_subtitle_disconnected = 4; const val tile_subtitle_connecting = 5
} }
''',
    "trace.kt": r'''
package com.silent.vpn.util
object SessionTrace {
    fun warn(tag: String, msg: String) {}; fun mark(tag: String, msg: String = "") {}
    fun enter(tag: String) {}; fun exit(tag: String, msg: String) {}
}

object DebugLog { fun w(tag: String, msg: String) {} }
''',
    "prefs.kt": r'''
package com.silent.vpn.data
import android.content.Context
object SilentPrefs { val prefs = Prefs(); fun open(context: Context) = prefs }
class Prefs {
    val values = mutableMapOf<String, Boolean>()
    fun getBoolean(key: String, fallback: Boolean) = values[key] ?: fallback
    fun edit() = Editor(this)
}
class Editor(val prefs: Prefs) {
    fun putBoolean(key: String, value: Boolean): Editor { prefs.values[key] = value; return this }
    fun commit() = true
}
''',
    "managers.kt": r'''
package com.silent.vpn.vpn
import kotlinx.coroutines.flow.MutableStateFlow
object WdttTunnelManager {
    val running = MutableStateFlow(false); val tunnelReady = MutableStateFlow(false)
    var strictReady = false; var captcha = false
    fun isTransportReadyStrict() = strictReady
    fun isCaptchaInProgress() = captcha
    fun clearStaleSession() { running.value = false; tunnelReady.value = false }
}
object OlcrtcTunnelManager {
    val running = MutableStateFlow(false); val tunnelReady = MutableStateFlow(false)
}
''',
    "captcha.kt": r'''
package com.silent.vpn.vpn.captcha
import android.content.Context
object ManlCaptchaWebViewManager {
    var isCaptchaPending = false; var shows = 0
    fun checkAndShowPendingCaptcha(context: Context) { shows++ }
}
''',
    "service.kt": r'''
package com.silent.vpn.service
import android.content.*
object SilentVpnService {
    var isRunning = false
    const val ACTION_DISCONNECT = "DISCONNECT"; const val ACTION_CONNECT = "CONNECT"
    fun resetStaleSession() { isRunning = false }
}
object VpnTileConnect {
    var cacheAvailable = true
    fun isCaptchaPending() = VpnSessionState.isCaptchaPending()
    fun buildConnectIntentFromCache(context: Context): Intent? =
        if (cacheAvailable) Intent().apply { action = SilentVpnService.ACTION_CONNECT } else null
}
object VpnBackendSync { fun stop() {} }
object VpnConnectHelper { fun noteCleanSlate() {} }
''',
    "test.kt": r'''
package harness
import android.os.Handler
import android.os.Build
import android.net.VpnService
import android.service.quicksettings.*
import com.silent.vpn.service.*
import com.silent.vpn.vpn.*
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*

@OptIn(ExperimentalCoroutinesApi::class)
fun main() {
    Dispatchers.setMain(UnconfinedTestDispatcher())
    var failed = 0
    fun test(name: String, block: () -> Unit) {
        try { block(); println("PASS $name") } catch (e: Throwable) { failed++; println("FAIL $name: ${e.message}") }
    }
    val tile = SilentVpnTileService()
    SilentVpnService.isRunning = true
    WdttTunnelManager.running.value = true
    WdttTunnelManager.strictReady = true
    WdttTunnelManager.tunnelReady.value = true
    tile.onStartListening()
    test("connected WDTT is enabled") { check(tile.qsTile!!.state == Tile.STATE_ACTIVE) }
    WdttTunnelManager.strictReady = false
    WdttTunnelManager.tunnelReady.value = false
    test("network gap preserves enabled tile") { check(tile.qsTile!!.state == Tile.STATE_ACTIVE) { "VPN service remains enabled but QS shows OFF" } }
    tile.onClick()
    test("click during recovery stops current session") { check(tile.started.last().action == "DISCONNECT") { "QS click sent ${tile.started.last().action} to already enabled VPN" } }
    WdttTunnelManager.running.value = false
    test("paused native transport remains enabled") {
        check(tile.qsTile!!.state == Tile.STATE_ACTIVE)
        check(tile.qsTile!!.subtitle == "5")
    }
    SilentVpnService.isRunning = false
    VpnTileHelper.requestUpdate(tile)
    test("service stop updates bound tile without native flow emission") { check(tile.qsTile!!.state == Tile.STATE_INACTIVE) }
    SilentVpnService.isRunning = true
    OlcrtcTunnelManager.running.value = true
    OlcrtcTunnelManager.tunnelReady.value = true
    test("RTC readiness uses same enabled switch") {
        check(tile.qsTile!!.state == Tile.STATE_ACTIVE)
        check(tile.qsTile!!.subtitle == "3")
    }
    OlcrtcTunnelManager.tunnelReady.value = false
    tile.onClick()
    test("RTC recovery click disconnects") { check(tile.started.last().action == "DISCONNECT") }
    ManlCaptchaWebViewManager.isCaptchaPending = true
    VpnTileHelper.requestUpdate(tile)
    val startedBeforeCaptcha = tile.started.size
    tile.onClick()
    test("captcha opens prompt without starting a second session") {
        check(tile.qsTile!!.subtitle == "2")
        check(ManlCaptchaWebViewManager.shows == 1)
        check(tile.started.size == startedBeforeCaptcha)
    }
    ManlCaptchaWebViewManager.isCaptchaPending = false
    OlcrtcTunnelManager.running.value = false
    tile.onStopListening()
    SilentVpnService.isRunning = false
    WdttTunnelManager.running.value = false
    OlcrtcTunnelManager.tunnelReady.value = true
    tile.onStartListening()
    test("dead owner cannot display stale RTC readiness as enabled") { check(tile.qsTile!!.state == Tile.STATE_INACTIVE) { "dead VPN service still shows ON" } }
    tile.onStopListening()
    OlcrtcTunnelManager.tunnelReady.value = false
    // Flush the previous scenario's trailing refresh, then start after its interval.
    Handler.advanceBy(2_500)
    Handler.advanceBy(2_500)
    val before = TileService.requests
    VpnTileHelper.requestUpdate(tile)
    VpnTileHelper.requestUpdate(tile)
    Handler.advanceBy(2_500)
    test("throttled final update is eventually delivered") { check(TileService.requests - before == 2) { "last state update lost; delivered=${TileService.requests - before}" } }
    tile.onStartListening()
    tile.onStartListening()
    val beforeFlowChange = tile.qsTile!!.updates
    SilentVpnService.isRunning = true
    WdttTunnelManager.running.value = true
    test("repeated listening replaces previous collector") { check(tile.qsTile!!.updates - beforeFlowChange == 1) }
    tile.onStopListening()
    val beforeStop = tile.qsTile!!.updates
    SilentVpnService.isRunning = false
    WdttTunnelManager.running.value = false
    VpnTileHelper.requestUpdate(tile)
    test("stopped listener does not retain live collector") { check(tile.qsTile!!.updates == beforeStop) }
    tile.onStartListening()
    test("rebound tile reads current stopped session") { check(tile.qsTile!!.state == Tile.STATE_INACTIVE) }
    tile.isLocked = true
    val beforeLocked = tile.started.size
    tile.onClick()
    test("locked screen defers command until unlock") { check(tile.started.size == beforeLocked) }
    tile.pendingUnlock!!.run()
    test("unlock starts cached VPN through foreground service") { check(tile.started.last().action == "CONNECT") }
    tile.isLocked = false
    VpnService.permissionNeeded = true
    val beforePermission = tile.started.size
    val openedBeforePermission = tile.openedActivities
    tile.onClick()
    test("missing VPN permission opens app without a connect command") {
        check(tile.started.size == beforePermission)
        check(tile.openedActivities == openedBeforePermission + 1)
    }
    VpnService.permissionNeeded = false
    VpnTileConnect.cacheAvailable = false
    val openedBeforeCache = tile.openedActivities
    tile.onClick()
    test("missing account config opens app without a connect command") {
        check(tile.started.size == beforePermission)
        check(tile.openedActivities == openedBeforeCache + 1)
    }
    VpnTileConnect.cacheAvailable = true
    Build.VERSION.SDK_INT = 24
    SilentVpnService.isRunning = true
    VpnTileHelper.requestUpdate(tile)
    test("API24 keeps enabled state without subtitle support") { check(tile.qsTile!!.state == Tile.STATE_ACTIVE) }
    tile.onDestroy()
    Dispatchers.resetMain()
    check(failed == 0) { "$failed tile regression scenarios failed" }
}
''',
}

CAPTCHA_DOUBLES = {
    "notification.kt": r'''
package androidx.core.app
import android.app.PendingIntent
import android.content.Context
object NotificationCompat {
    const val PRIORITY_HIGH = 1
    class Builder(context: Context, id: String) {
        fun setSmallIcon(icon: Int) = this
        fun setContentTitle(title: String) = this
        fun setContentText(text: String) = this
        fun setPriority(priority: Int) = this
        fun setContentIntent(intent: PendingIntent) = this
        fun setAutoCancel(enabled: Boolean) = this
        fun addAction(icon: Int, title: String, intent: PendingIntent) = this
        fun build(): Any = Any()
    }
}
''',
    "android_r.kt": r'''
package android
object R { object drawable { const val ic_dialog_alert = 1 } }
''',
    "captcha_activity.kt": r'''
package com.silent.vpn.vpn.captcha
import android.content.Context
class ManlCaptchaActivity: Context() { fun finish() {} }
class CaptchaCancelReceiver
''',
    "test.kt": r'''
package harness
import android.service.quicksettings.*
import com.silent.vpn.service.*
import com.silent.vpn.vpn.captcha.ManlCaptchaWebViewManager
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*

@OptIn(ExperimentalCoroutinesApi::class)
fun main() {
    val dispatcher = UnconfinedTestDispatcher()
    Dispatchers.setMain(dispatcher)
    val scope = CoroutineScope(SupervisorJob() + dispatcher)
    var failed = 0
    fun test(name: String, block: () -> Unit) {
        try { block(); println("PASS $name") } catch (e: Throwable) { failed++; println("FAIL $name: ${e.message}") }
    }
    val tile = SilentVpnTileService()
    SilentVpnService.isRunning = true
    tile.onStartListening()
    val solve = scope.async { ManlCaptchaWebViewManager.solveCaptchaAsync(tile, "fixture", "fixture") }
    test("actual captcha pending lifecycle updates bound QS subtitle") {
        check(ManlCaptchaWebViewManager.isCaptchaPending)
        check(tile.qsTile!!.subtitle == "2") { "pending manual captcha did not refresh tile" }
    }
    VpnTileHelper.requestUpdate(tile)
    ManlCaptchaWebViewManager.notifyResult(Result.success("token"))
    test("actual captcha completion removes pending subtitle") {
        check(solve.isCompleted)
        check(!ManlCaptchaWebViewManager.isCaptchaPending)
        check(tile.qsTile!!.subtitle == "5") { "completed captcha subtitle remains stuck" }
    }
    val cancelled = scope.async { ManlCaptchaWebViewManager.solveCaptchaAsync(tile, "fixture", "fixture") }
    VpnTileHelper.requestUpdate(tile)
    ManlCaptchaWebViewManager.cancelCaptcha()
    test("actual cancellation updates QS without waiting for readiness") {
        check(cancelled.isCompleted)
        check(!ManlCaptchaWebViewManager.isCaptchaPending)
        check(tile.qsTile!!.subtitle == "5") { "cancelled captcha subtitle remains stuck" }
    }
    tile.failActivityLaunch = true
    val rejected = scope.async { ManlCaptchaWebViewManager.solveCaptchaAsync(tile, "fixture", "fixture") }
    test("failed activity launch clears actual pending state") {
        check(rejected.isCompleted)
        check(!ManlCaptchaWebViewManager.isCaptchaPending) { "failed launch leaked pending captcha" }
        check(tile.qsTile!!.subtitle == "5")
    }
    tile.onDestroy()
    scope.cancel()
    Dispatchers.resetMain()
    check(failed == 0) { "$failed captcha regression scenarios failed" }
}
''',
}

def main():
    compiler = [
        jar("org.jetbrains.kotlin", "kotlin-compiler-embeddable", "2.0.21"),
        jar("org.jetbrains.kotlin", "kotlin-stdlib", "2.0.21"),
        jar("org.jetbrains.kotlin", "kotlin-script-runtime", "2.0.21"),
        jar("org.jetbrains.kotlin", "kotlin-reflect"),
        jar("org.jetbrains.intellij.deps", "trove4j"),
        jar("org.jetbrains", "annotations"),
        jar("org.jetbrains.kotlinx", "kotlinx-coroutines-core-jvm"),
    ]
    runtime = [compiler[1], compiler[-2], compiler[-1], jar("org.jetbrains.kotlinx", "kotlinx-coroutines-test-jvm")]
    source_dir = ROOT / "app/src/main/kotlin/com/silent/vpn/service"
    sources = [source_dir / name for name in (
        "SilentVpnTileService.kt", "VpnTileHelper.kt", "VpnServiceTracker.kt", "VpnSessionState.kt",
    )]
    sources += list(source_dir.glob("VpnTile*Policy.kt"))
    sources += list(source_dir.glob("VpnTile*Gate.kt"))
    with tempfile.TemporaryDirectory(prefix="silent-tile-") as directory:
        temp = Path(directory)
        doubles = dict(DOUBLES)
        if "--captcha" in sys.argv:
            doubles.pop("captcha.kt")
            doubles.update(CAPTCHA_DOUBLES)
            captcha_source = ROOT / "app/src/main/kotlin/com/silent/vpn/vpn/captcha/ManlCaptchaWebViewManager.kt"
            source = captcha_source.read_text(encoding="utf-8")
            # Compile the production manager object verbatim; the UI Activity follows it
            # in the same file and is replaced with an Android activity double.
            manager = source[source.index("object ManlCaptchaWebViewManager {"):source.index("class ManlCaptchaActivity :")]
            doubles["captcha_manager.kt"] = """package com.silent.vpn.vpn.captcha
import android.app.*
import android.content.*
import android.util.Log
import androidx.core.app.NotificationCompat
import com.silent.vpn.service.VpnTileHelper
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.*
import java.util.concurrent.atomic.AtomicReference
""" + manager
        for name, content in doubles.items():
            target = temp / name
            target.write_text(content.strip() + "\n", encoding="utf-8")
            sources.append(target)
        classes = temp / "classes"
        args = [str(JAVA), "-cp", os.pathsep.join(compiler), "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
                "-no-stdlib", "-no-reflect", "-jvm-target", "17", "-cp", os.pathsep.join(runtime),
                "-d", str(classes), *map(str, sources)]
        subprocess.run(args, check=True)
        result = subprocess.run([str(JAVA), "-cp", os.pathsep.join([str(classes), *runtime]), "harness.TestKt"])
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
