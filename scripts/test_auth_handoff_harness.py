"""Compile actual auth reconciliation/countdown methods against deterministic tunnel doubles."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
from test_tile_state_harness import ROOT, JAVA, jar


def method(source, name):
    start = re.search(r'(?m)^\s*(?:private |override )?fun '+re.escape(name)+r'\(', source).start()
    opening = source.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    source = (ROOT/'app/src/main/kotlin/com/silent/vpn/MainViewModel.kt').read_text(encoding='utf-8')
    methods = '\n'.join(method(source, n) for n in (
        'ensureBootstrapForAuthFlow', 'reconcileLoginBootstrapSession',
        'updateBootstrapReadyFlag', 'refreshBootstrapCountdownNow'))
    fixture = r'''
package harness
class Box<T>(var value: T)
class Context { val applicationContext get() = this }
enum class AppScreen { LOGIN, MAIN }
enum class VpnState { CONNECTED, CONNECTING, DISCONNECTED, DISCONNECTING }
object SilentVpnService { var isRunning = true }
object WdttTunnelManager {
 val tunnelReady = Box(true); val activeWorkers = Box(2); var bootstrap = false
 fun isBootstrapMode() = bootstrap
 fun lastWgAddress(): String? = null
}
object DebugLog { fun i(tag: String, msg: String) {} }
class Repo {
 var loggedIn = false
 fun isLoggedIn() = loggedIn
 fun setTunnelApiFromWgAddress(address: String) {}
 fun ensureBootstrapTunnelApi() {}
}
class Fixture {
 val repo = Repo(); val _bootstrapExpired = Box(false); val _bootstrapReady = Box(false)
 val _screen = Box(AppScreen.LOGIN); val _vpnState = Box(VpnState.DISCONNECTED)
 val _bootstrapSecondsLeft = Box<Int?>(null); val _statusMsg = Box("")
 val _regDone = Box(false); val _forgotSent = Box(false)
 var bootstrapVpnMode = false; var bootstrapContext: Context? = null
 var bootstrapDeadlineMs = 0L; var bootstrapConnectingInternal = false
 var logoutTransitionActive = false; var starts = 0; var timers = 0
 fun isHashReady() = true
 fun bootstrapRequiresActiveWorkers() = false
 fun onVpnTunnelReady(initialConnect: Boolean = false) {}
 fun startBootstrapSessionTimeout(ctx: Context, forceNewDeadline: Boolean = false) { timers++; bootstrapDeadlineMs = System.currentTimeMillis()+120_000; refreshBootstrapCountdownNow() }
 fun cancelBootstrapSessionTimeout() { _bootstrapSecondsLeft.value = null }
 fun ensureBootstrapVpn(ctx: Context) { starts++ }
 fun refresh() = refreshBootstrapCountdownNow()
METHODS
}
fun main() {
 var failures = 0
 fun scenario(name: String, block: () -> Unit) {
  try { block(); println("PASS $name") } catch (e: Throwable) { failures++; println("FAIL $name: ${e.message}") }
 }
 scenario("old authenticated tunnel must not become green login bootstrap") {
  WdttTunnelManager.bootstrap=false; WdttTunnelManager.tunnelReady.value=true
  val f=Fixture(); f.reconcileLoginBootstrapSession(Context())
  check(!f._bootstrapReady.value && f.timers==0 && !f.bootstrapVpnMode)
 }
 scenario("logout handoff ignores stale ready bootstrap") {
  WdttTunnelManager.bootstrap=true
  val f=Fixture(); f.logoutTransitionActive=true; f.ensureBootstrapForAuthFlow(Context())
  check(!f._bootstrapReady.value && f.timers==0 && f.starts==0)
 }
 scenario("real bootstrap can be reattached after handoff") {
  val f=Fixture(); f.ensureBootstrapForAuthFlow(Context())
  check(f._bootstrapReady.value && f.timers==1 && f.starts==0)
 }
 scenario("lost transport clears green countdown immediately") {
  val f=Fixture(); f.reconcileLoginBootstrapSession(Context())
  WdttTunnelManager.tunnelReady.value=false; f.refresh()
  check(!f._bootstrapReady.value && f._bootstrapSecondsLeft.value==null)
 }
 check(failures==0) { "$failures auth handoff regressions" }
}
'''.replace('METHODS', methods)
    compiler = [jar('org.jetbrains.kotlin','kotlin-compiler-embeddable','2.0.21'),
                jar('org.jetbrains.kotlin','kotlin-stdlib','2.0.21'),
                jar('org.jetbrains.kotlin','kotlin-script-runtime','2.0.21'),
                jar('org.jetbrains.kotlin','kotlin-reflect'),jar('org.jetbrains.intellij.deps','trove4j'),
                jar('org.jetbrains','annotations'),jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm')]
    with tempfile.TemporaryDirectory(prefix='silent-auth-handoff-') as folder:
        path=Path(folder); src=path/'Fixture.kt';src.write_text(fixture,encoding='utf-8')
        classes=path/'classes'
        subprocess.run([str(JAVA),'-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
                        '-no-stdlib','-no-reflect','-jvm-target','17','-cp',os.pathsep.join(compiler[1:]),
                        '-d',str(classes),str(src)],check=True)
        result=subprocess.run([str(JAVA),'-cp',os.pathsep.join([str(classes),*compiler[1:]]),'harness.FixtureKt'])
        raise SystemExit(result.returncode)


if __name__=='__main__': main()
