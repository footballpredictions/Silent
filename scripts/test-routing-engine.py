"""Test the actual iOS flow-TUN core without Apple's SDK (not an iOS build).

Only the C output callback is replaced; DNS interception, routing, queues and
shutdown are extracted unchanged from engine/ios_export.go. Artifacts stay in
the monorepo's ignored .playwright-mcp directory.
"""
from pathlib import Path
import os
import shutil
import subprocess

root = Path(__file__).resolve().parents[2]
native = root / "android/app/site-router"
target = root / ".playwright-mcp/ios-routing-engine-test"
target.mkdir(parents=True, exist_ok=True)
for name in ("go.mod", "go.sum", "packet.go", "russian.go", "russian_test.go"):
    shutil.copyfile(native / name, target / name)
direct = (native / "direct.go").read_text(encoding="utf-8")
(target / "direct.go").write_text(direct.split("\n", 1)[1], encoding="utf-8")
source = (root / "ios/engine/ios_export.go").read_text(encoding="utf-8")
core = source[source.index("type russianFlow struct"):]
callback = "C.call_output(cb, (*C.uchar)(unsafe.Pointer(&packet[0])), C.int(len(packet)))"
assert core.count(callback) == 1
core = core.replace(callback, "cb(packet)")
prefix = '''package main
import ("context"; "net/netip"; "os"; "sync"; "time"; "golang.zx2c4.com/wireguard/tun")
var engineMu sync.Mutex
var outputCb func([]byte)
'''
(target / "ios_flow.go").write_text(prefix + core, encoding="utf-8")
(target / "ios_flow_test.go").write_text('''package main
import ("bytes"; "context"; "testing"; "time"; "net/netip")
func TestIOSFlowInterceptsRussianDNSAndKeepsForeignPacketInWireGuard(t *testing.T) {
    flow := newFlowTUN(1200)
    defer flow.Close()
    replies := make(chan []byte, 2)
    outputCb = func(p []byte) { replies <- append([]byte(nil), p...) }
    defer func() { outputCb = nil }()
    ip := [4]byte{203, 0, 113, 8}
    flow.russian.update(russianConfig{Enabled:true, Direct:[]string{"ru"}})
    flow.russian.exchange = func(context.Context, []byte) ([]byte,error) { return ruFixture("shop.ru",true,ip)[28:],nil }
    foreign := ruFixture("example.com",false,ip)
    flow.in <- ruFixture("shop.ru",false,ip)
    flow.in <- foreign
    buf := make([]byte,65535)
    sizes := make([]int,1)
    n,err := flow.Read([][]byte{buf},sizes,0)
    if err != nil || n != 1 || !bytes.Equal(buf[:sizes[0]],foreign) { t.Fatal("Foreign DNS did not stay in WG") }
    select {
    case reply := <-replies:
        if _,_,ok := russianDNS(reply,true); !ok || !flow.russian.direct(netip.AddrFrom4(ip)) { t.Fatal("DNS reply arrived before its DIRECT rule") }
    case <-time.After(time.Second): t.Fatal("No RU DNS response")
    }
}
func TestIOSWireGuardResponseWarmsRussianCacheBeforeDelivery(t *testing.T) {
    flow := newFlowTUN(1200)
    defer flow.Close()
    ip := [4]byte{203,0,113,9}
    flow.russian.update(russianConfig{Enabled:true, Direct:[]string{"ru"}})
    outputCb = func([]byte) { if !flow.russian.direct(netip.AddrFrom4(ip)) { t.Error("Unlearned response delivered") } }
    defer func() { outputCb = nil }()
    response := ruFixture("shop.ru",true,ip)
    if _,err := flow.Write([][]byte{response},0); err != nil { t.Fatal(err) }
}
''', encoding="utf-8")
environment = dict(os.environ, CGO_ENABLED="0")
subprocess.run(["go", "test", "-v", "./..."], cwd=target, env=environment, check=True)
