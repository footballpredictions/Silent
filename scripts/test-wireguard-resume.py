"""Exercise the actual wake bridge with real WireGuard devices and UDP sockets."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'engine/ios_export.go').read_text(encoding='utf-8')
start = source.index('func wdtt_network_event(')
opening = source.index('{', start)
depth = 1
end = opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
bridge = source[start:end].replace('C.int', 'int')
with tempfile.TemporaryDirectory(prefix='silent-wg-resume-') as directory:
    target = Path(directory)
    (target / 'go.mod').write_text('module wireguard-resume\n\ngo 1.26\n\nrequire golang.zx2c4.com/wireguard v0.0.0-20261006164505-2631ce99a06f\n')
    (target / 'bridge.go').write_text('''package main
import("sync"; "strings"; "golang.zx2c4.com/wireguard/device")
var engineMu,engineLifeMu sync.Mutex
var engineDev *device.Device
type networkEvents struct{}
func(networkEvents)notify(bool)bool{return true}
var iosPathEvents networkEvents
func writeIOSJournal(string,int){}
''' + bridge, encoding='utf-8')
    (target / 'resume_test.go').write_bytes((root / 'scripts/fixtures/wireguard/resume_test.go').read_bytes())
    subprocess.run(['go','test','-mod=mod','-count=1','-v','./...'],cwd=target,check=True,timeout=120)
