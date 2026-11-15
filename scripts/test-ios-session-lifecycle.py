"""Run the actual DTLS keepalive loop with a failed socket, without VK or an iOS SDK.

Only the surrounding TURN/DTLS setup is replaced by fixtures. The goroutine is
extracted verbatim, so this checks that a failed keepalive releases the session
which owns the registered worker, instead of leaving it stuck in proxyWg.Wait.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1]).read_text(encoding="utf-8")
start = source.index("\tgo func() {", source.index("// DTLS Keepalive + periodic GETCONF"))
end = source.index("\n\t// Writer: dispatcher", start)
loop = source[start:end]
writer_start = source.index("\tgo func() {", source.index("// Writer: dispatcher"))
writer_end = source.index("\n\t// Reader: DTLS", writer_start)
writer_loop = source[writer_start:writer_end]
binding_start = source.index("\tgo func() {", source.index("// Keepalive goroutine (TURN binding request)"))
binding_end = source.index("\n\t// Relay ↔ Pipe proxy", binding_start)
binding_loop = source[binding_start:binding_end].replace("10 * time.Second", "5 * time.Millisecond")
binding_loop = binding_loop.replace("runIOSBindingChecks(", "runTestIOSBindingChecks(")
with tempfile.TemporaryDirectory(prefix="silent-session-") as directory:
    target = Path(directory)
    (target / "go.mod").write_text("module session-lifecycle\n\ngo 1.26\n\nrequire github.com/pion/logging v0.2.4\n", encoding="utf-8")
    prefix = '''package main
import ("context"; "log"; "sync"; "time")
const keepaliveInterval = 5*time.Millisecond
const accessCheckInterval = 7*time.Millisecond
const keepaliveByte = 0xFF
func getconfPayload(_, _, _ string) []byte { return []byte("GETCONF") }
type keepaliveConn interface { Write([]byte) (int,error); SetWriteDeadline(time.Time) error }
func launchKeepalive(parent context.Context, dtlsConn keepaliveConn, getConfig bool) (context.Context, context.CancelFunc, <-chan struct{}) {
    sessCtx, sessCancel := context.WithCancel(parent)
    var proxyWg sync.WaitGroup
    proxyWg.Add(1)
    deviceID, password, localPort, sessionID := "fixture", "fixture", "0", 1
'''
    suffix = '''
    done := make(chan struct{})
    go func() { proxyWg.Wait(); close(done) }()
    return sessCtx, sessCancel, done
}
'''
    (target / "keepalive.go").write_text(prefix + loop + suffix, encoding="utf-8")
    writer_prefix = '''package main
import ("context"; "log"; "sync"; "time")
const sessionReadTimeout = 30*time.Minute
func putPktBuf([]byte) {}
func launchWriter(parent context.Context, dtlsConn keepaliveConn, packets <-chan []byte) (context.Context, context.CancelFunc, <-chan struct{}) {
    sessCtx, sessCancel := context.WithCancel(parent)
    sessionID := 1
    slot := struct{SendCh <-chan []byte}{packets}
    var proxyWg sync.WaitGroup
    proxyWg.Add(1)
'''
    (target / "writer.go").write_text(writer_prefix + writer_loop + suffix, encoding="utf-8")
    relay_read = source.index("n, _, readErr := relay.ReadFrom(buf)")
    failure_start = source.index("\t\t\tif readErr != nil {", relay_read)
    failure_end = source.index("\n\t\t\t}", failure_start) + len("\n\t\t\t}")
    failure = source[failure_start:failure_end]
    failure_imports = '"context"; "log"' if 'log.' in failure else '"context"'
    (target / "relay_failure.go").write_text(
        f'package main\nimport ({failure_imports})\n'
        'func reportRelayReadFailure(sessCtx context.Context,readErr error){\nsessionID:=1\n_ = sessionID\n'
        + failure + '\n}\n', encoding="utf-8")
    binding_prefix = '''package main
import ("context"; "net"; "sync"; "time")
type bindingQuality struct{}
func (*bindingQuality) observe(time.Duration,error,time.Time) {}
func runTestIOSBindingChecks(ctx context.Context, id int, probe func()(net.Addr,error), cancel context.CancelFunc, activity *iosSessionActivity, resume func() error) {
    timer := time.NewTicker(5*time.Millisecond)
    defer timer.Stop()
    runIOSBindingLoop(ctx,id,probe,cancel,timer.C,&iosPathEvents,activity,resume)
}
func launchBinding(parent context.Context, tc *testTURNConnection) (context.Context,context.CancelFunc,<-chan struct{}) {
    sessCtx,sessCancel := context.WithCancel(parent)
    sessionID := 1
    _ = sessionID
    activity := &iosSessionActivity{}
    _ = activity
    relay := tc
    _ = relay
    var quality *bindingQuality
    var sessionWg sync.WaitGroup
    sessionWg.Add(1)
'''
    binding_suffix = '''
    done := make(chan struct{})
    go func(){sessionWg.Wait();close(done)}()
    return sessCtx,sessCancel,done
}
'''
    (target / "binding.go").write_text(binding_prefix + binding_loop + binding_suffix, encoding="utf-8")
    registration = source[source.index("\td.Register(slot)"):source.index("\n\t// Proxy DTLS")]
    imports = '"context"; "sync"' if 'sync.' in registration else '"context"'
    wrapper = f'package main\nimport ({imports})\n'
    wrapper += 'func holdRegistration(sessCtx context.Context,d *testDispatcher,slot *testWorkerSlot,ready chan struct{},hold <-chan struct{}) {\nactivity := &iosSessionActivity{}\n_ = activity\n'
    wrapper += registration + '\nclose(ready)\n<-hold\n}\n'
    (target / "registration.go").write_text(wrapper, encoding="utf-8")
    shutil.copyfile(root / "engine/network_lifecycle.go", target / "network_lifecycle.go")
    logger_start = source.index("type NullLoggerFactory struct{}")
    logger_end = source.index("// connectedUDPConn", logger_start)
    factory = "&NullLoggerFactory{}"
    if "LoggerFactory:          &iosTURNLoggerFactory{" in source:
        factory = "&iosTURNLoggerFactory{ctx:ctx, cancel:cancel, sessionID:1}"
        shutil.copyfile(root / "engine/turn_lifecycle.go", target / "turn_lifecycle.go")
    logger = 'package main\nimport ("context"; "github.com/pion/logging")\n' + source[logger_start:logger_end]
    logger += 'func sessionTURNLogger(ctx context.Context, cancel context.CancelFunc) logging.LeveledLogger {\n'
    logger += f'factory := {factory}\nreturn factory.NewLogger("turn")\n}}\n'
    (target / "logger.go").write_text(logger, encoding="utf-8")
    shutil.copyfile(root / "scripts/fixtures/session/keepalive_test.go", target / "keepalive_test.go")
    result = subprocess.run(["go", "test", "-mod=mod", "-count=1", "-v", "./..."], cwd=target, timeout=60)
    sys.exit(result.returncode)
