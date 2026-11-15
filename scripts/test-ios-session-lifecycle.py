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
