"""Exercise actual iOS session loops against the deployed server's DTLS idle rule.

Only TURN setup/access accounting are fixtures. DTLS, UDP listener/CID and the
server proxy are real. A fake wall clock advances past the server's 90s lifetime
while the server test deadline is accelerated to 90ms. No public network is used.
"""
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
import tempfile


root = Path(__file__).resolve().parents[1]
if len(sys.argv) > 1:
    source = Path(sys.argv[1]).read_text(encoding="utf-8")
else:
    spec = importlib.util.spec_from_file_location("ios_adapter", root / "scripts/adapt-ios-session.py")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    source = adapter.adapt((root.parent / "android/app/wdtt-go/session.go").read_text(encoding="utf-8"))

fixture = root / "scripts/fixtures/session"
server = (fixture / "server_proxy.go.fixture").read_text(encoding="utf-8")
backend = root.parent / "backend/wdtt-src/server.go"
if backend.exists():
    actual = backend.read_text(encoding="utf-8")
    start = actual.index("\t// WG прокси", actual.index("func handleConn("))
    end = actual.index("\nconst (\n\twrapNonceLen", start)
    assert server[server.index("\t// WG прокси"):] == actual[start:end], "Refresh the reviewed server proxy fixture"
assert server.count("90 * time.Second") == 1
server = server.replace("90 * time.Second", "90 * time.Millisecond")

keepalive = source[source.index("\tgo func() {", source.index("// DTLS Keepalive + periodic GETCONF")):source.index("\n\t// Writer: dispatcher")]
keepalive = keepalive.replace("time.NewTicker(keepaliveInterval)", "ticks.pingTicker()")
keepalive = keepalive.replace("time.NewTicker(accessCheckInterval)", "ticks.accessTicker()")
writer = source[source.index("\tgo func() {", source.index("// Writer: dispatcher")):source.index("\n\t// Reader: DTLS")]
reader = source[source.index("\tgo func() {", source.index("// Reader: DTLS")):source.index("\n\tproxyWg.Wait()")]
registration = source[source.index("\td.Register(slot)"):source.index("\n\t// Proxy DTLS")]

# Extract the actual post-handshake wrapper installation as well as all writes.
# The unpatched source intentionally still compiles, to prove this test is RED
# on the old connection which only checks successful local writes/STUN.
installation = "dtlsConn := rawDTLSConn\n"
if "\tdtlsConn := newIOSDTLSConn(rawDTLSConn" in source:
    start = source.index("\tdtlsConn := newIOSDTLSConn(rawDTLSConn")
    end = source.index("\n\n\tstats.IncActive()", start)
    installation = source[start:end].replace("newIOSDTLSConn(rawDTLSConn,", "newIOSDTLSConnWithClock(rawDTLSConn, clock.now,") + "\n"
    installation += "ticks.settle = func(){dtlsConn.sendMu.Lock();dtlsConn.sendMu.Unlock()}\n"

prefix = '''package main
import ("context";"log";"net";"sync";"time")
const keepaliveByte=0xFF
const sessionReadTimeout=30*time.Minute
func getPktBuf(n int)[]byte{return make([]byte,n)}
func putPktBuf([]byte){}
func launchActualClient(parent context.Context,rawDTLSConn net.Conn,d *testDispatcher,slot *testWorkerSlot,activity *iosSessionActivity,clock *fixtureWallClock,ticks *fixtureTicks)(context.Context,context.CancelFunc,<-chan struct{}){
sessCtx,sessCancel:=context.WithCancel(parent)
sessionID:=1
deviceID,password,localPort:="fixture","fixture","0"
getConfig:=true
ready,done:=make(chan struct{}),make(chan struct{})
'''
suffix = '''
go func(){
defer close(done)
''' + registration + '''
var proxyWg sync.WaitGroup
proxyWg.Add(3)
stopDTLS:=context.AfterFunc(sessCtx,func(){_ = dtlsConn.Close()})
defer stopDTLS()
close(ready)
''' + keepalive + writer + reader + '''
proxyWg.Wait()
}()
<-ready
return sessCtx,sessCancel,done
}
'''

with tempfile.TemporaryDirectory(prefix="silent-dtls-idle-") as directory:
    target = Path(directory)
    (target / "go.mod").write_text("""module session-dtls-idle

go 1.26

require (
 github.com/pion/dtls/v3 v3.1.2
 github.com/pion/transport/v4 v4.0.1
 golang.org/x/crypto v0.46.0
 golang.org/x/net v0.48.0
)
""", encoding="utf-8")
    (target / "client_actual.go").write_text(prefix + installation + suffix, encoding="utf-8")
    (target / "server_actual.go").write_text(server, encoding="utf-8")
    shutil.copyfile(root / "engine/network_lifecycle.go", target / "network_lifecycle.go")
    shutil.copyfile(root.parent / "android/app/wdtt-go/protocol.go", target / "protocol.go")
    shutil.copyfile(fixture / "dtls_idle_test.go", target / "dtls_idle_test.go")
    helper_tests = fixture / "dtls_send_test.go"
    if helper_tests.exists():
        shutil.copyfile(helper_tests, target / "dtls_send_test.go")
    result = subprocess.run(["go", "test", "-mod=mod", "-count=1", "-v", *sys.argv[2:], "./..."], cwd=target, timeout=90)
    sys.exit(result.returncode)
