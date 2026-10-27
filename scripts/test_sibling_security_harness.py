"""Exercise the production exported receiver against forged broadcasts and a blocked cleanup."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
from test_tile_state_harness import ROOT, JAVA, jar
from test_auth_handoff_harness import method

DOUBLES = {
 'android.kt': '''package android.content
import android.app.PendingIntent
open class Context {
 val applicationContext get()=this; val packageName="com.silent.vpn"
 fun startService(i: Intent) {}
}
class Intent(val context: Context?=null,val klass: Class<*>?=null) {
 var action: String?=null; var proof: PendingIntent?=null
}
open class BroadcastReceiver {
 open fun onReceive(context: Context,intent: Intent?) {}
 fun goAsync(): PendingResult { calls++; return PendingResult() }
 class PendingResult { fun finish() { finishes++ } }
 companion object { var calls=0; @Volatile var finishes=0 }
}
''',
 'ssl.kt': '''package android.net.http
class SslError(val url:String?)
''',
 'web.kt': '''package android.webkit
class WebView
class SslErrorHandler {var proceeded=false;var cancelled=false;fun proceed(){proceeded=true};fun cancel(){cancelled=true}}
open class WebViewClient {open fun onReceivedSslError(view:WebView,handler:SslErrorHandler,error:android.net.http.SslError){}}
''',
 'pending.kt': '''package android.app
class PendingIntent(val creatorPackage: String)
''',
 'compat.kt': '''package androidx.core.content
import android.content.Intent
object IntentCompat {
 @Suppress("UNCHECKED_CAST")
 fun <T> getParcelableExtra(intent: Intent,key: String,klass: Class<T>): T? = intent.proof as T?
}
''',
 'log.kt': '''package com.silent.vpn.util
object DebugLog { fun w(tag: String,msg: String) {}; fun e(tag: String,msg: String) {} }
''',
 'vpn.kt': '''package com.silent.vpn.service
import android.content.Context
import java.util.concurrent.CountDownLatch
object VpnConnectHelper {
 @Volatile var cleanups=0; @Volatile var gate: CountDownLatch?=null
 var entered=CountDownLatch(1)
 suspend fun ensureCleanSlate(context: Context,force: Boolean) { cleanups++; entered.countDown();gate?.await() }
}
class SilentVpnService { companion object { const val ACTION_DISCONNECT="disconnect" } }
''',
 'test.kt': '''package harness
import android.app.PendingIntent
import android.content.*
import com.silent.vpn.policy.SiblingVpnPolicy
import com.silent.vpn.service.*
import java.util.concurrent.*
fun main() {
 var failures=0
 fun test(name: String,block: ()->Unit) { try { block();println("PASS $name") } catch(e:Throwable){failures++;println("FAIL $name: ${e.message}")} }
 if (STRICT_CAPTCHA) for (url in listOf("https://id.vk.ru/captcha", "https://evil.example/?next=vk.ru", "https://okcdn.ru/", "https://vk.com/")) test("reject invalid TLS for $url") {
  val handler=android.webkit.SslErrorHandler()
  CaptchaFixture().onReceivedSslError(android.webkit.WebView(),handler,android.net.http.SslError(url))
  check(handler.cancelled && !handler.proceeded)
 }
 val receiver=SiblingVpnTeardownReceiver();val ctx=Context()
 test("integrity verification exception must reject VPN") {
  check(!IntegrityFixture().ensureOkForVpn(ctx))
 }
 fun request(creator: String?): Intent = Intent().apply {action=SiblingVpnPolicy.ACTION_SIBLING_TEARDOWN;proof=creator?.let{PendingIntent(it)}}
 for (creator in listOf(null,"evil.app","com.silent.vpn")) test("reject forged creator=$creator") {
  val before=VpnConnectHelper.cleanups;receiver.onReceive(ctx,request(creator));check(VpnConnectHelper.cleanups==before)
 }
 test("trusted cleanup cannot block broadcast thread") {
  val gate=CountDownLatch(1);VpnConnectHelper.gate=gate;VpnConnectHelper.entered=CountDownLatch(1)
  val executor=Executors.newSingleThreadExecutor()
  val future=executor.submit {receiver.onReceive(ctx,request("com.silent.vpn.debug"))}
  try {
   check(VpnConnectHelper.entered.await(3,TimeUnit.SECONDS))
   val returned=try{future.get(1,TimeUnit.SECONDS);true}catch(e:TimeoutException){false}
   check(returned){"onReceive blocked waiting for VPN shutdown"}
  } finally {gate.countDown();future.get(3,TimeUnit.SECONDS);executor.shutdown()}
 }
 check(failures==0){"$failures receiver security regressions"}
}
'''
}

def main():
    compiler=[jar('org.jetbrains.kotlin','kotlin-compiler-embeddable','2.0.21'),jar('org.jetbrains.kotlin','kotlin-stdlib','2.0.21'),jar('org.jetbrains.kotlin','kotlin-script-runtime','2.0.21'),jar('org.jetbrains.kotlin','kotlin-reflect'),jar('org.jetbrains.intellij.deps','trove4j'),jar('org.jetbrains','annotations'),jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm')]
    with tempfile.TemporaryDirectory(prefix='silent-receiver-') as folder:
        tmp=Path(folder);sources=[]
        for name,content in DOUBLES.items():
            p=tmp/name;p.write_text(content.replace('STRICT_CAPTCHA', str('--strict-captcha-tls' in sys.argv).lower()),encoding='utf-8');sources.append(p)
        integrity_path='app/src/main/kotlin/com/silent/vpn/security/AppIntegrity.kt'
        integrity=(ROOT/integrity_path).read_text(encoding='utf-8')
        if '--baseline' in sys.argv:
            integrity=subprocess.check_output(['git','-C',str(ROOT),'show','HEAD:'+integrity_path]).decode('utf-8')
        p=tmp/'IntegrityFixture.kt'
        p.write_text('''package harness
import android.content.Context
import com.silent.vpn.util.DebugLog
object BuildConfig { const val DEBUG=false }
class IntegrityFixture {
 var checked=false;var ok=true;var failReason:String?=null
 fun verifyBlocking(context:Context) {throw java.io.IOException("fixture read failed")}
'''+method(integrity,'ensureOkForVpn')+'\n}',encoding='utf-8')
        sources.append(p)
        captcha_path='app/src/main/kotlin/com/silent/vpn/vpn/captcha/AutoCaptchaActivity.kt'
        captcha=(ROOT/captcha_path).read_text(encoding='utf-8')
        if '--baseline' in sys.argv:
            captcha=subprocess.check_output(['git','-C',str(ROOT),'show','HEAD:'+captcha_path]).decode('utf-8')
        p=tmp/'CaptchaFixture.kt'
        p.write_text('package harness\nimport android.webkit.*\nclass CaptchaFixture:WebViewClient(){\n'+method(captcha,'onReceivedSslError')+'\n}',encoding='utf-8')
        sources.append(p)
        receiver=ROOT/'app/src/main/kotlin/com/silent/vpn/service/SiblingVpnTeardownReceiver.kt'
        if '--baseline' in sys.argv:
            original=subprocess.check_output(['git','-C',str(ROOT),'show','HEAD:app/src/main/kotlin/com/silent/vpn/service/SiblingVpnTeardownReceiver.kt'])
            receiver=tmp/'Receiver.kt';receiver.write_bytes(original)
        sources += [receiver,ROOT/'app/src/main/kotlin/com/silent/vpn/policy/SiblingVpnPolicy.kt']
        classes=tmp/'classes'
        subprocess.run([str(JAVA),'-cp',os.pathsep.join(compiler),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-cp',os.pathsep.join(compiler[1:]),'-d',str(classes),*map(str,sources)],check=True)
        result=subprocess.run([str(JAVA),'-cp',os.pathsep.join([str(classes),*compiler[1:]]),'harness.TestKt'])
        raise SystemExit(result.returncode)

if __name__=='__main__': main()
