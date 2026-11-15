"""Install the actual session cancellation/relay attachment code in Pion's tests."""
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding='utf-8')
target = Path(sys.argv[2])
start = source.index('\tdefer turnConn.Close()') if '\tdefer turnConn.Close()' in source else source.index('\ttransport := newIOSTURNTransport(turnConn)')
setup = source[start:source.index('\tturnAddr :=', start)]
attach_start = source.index('\tdefer relay.Close()') if '\tdefer relay.Close()' in source else source.index('\tif !transport.attach(relay)')
attach = source[attach_start:source.index('\n\t// Reset error count', attach_start)]
wrapper = '''package turn
import ("context"; "net")
func iosCancelSessionFixture(sessCtx context.Context, turnConn, relay net.PacketConn, ready chan struct{}, release <-chan struct{}) (bool,error) {
'''
(target / 'ios_cleanup_fixture_test.go').write_text(wrapper + setup + attach + '\nclose(ready)\n<-release\nreturn false,sessCtx.Err()\n}\n', encoding='utf-8')
root = Path(__file__).resolve().parents[1]
owner = root / 'engine/turn_transport.go'
if owner.exists():
    (target / 'ios_transport_fixture_test.go').write_text(owner.read_text(encoding='utf-8').replace('package main', 'package turn', 1), encoding='utf-8')
(target / 'ios_cleanup_test.go').write_text((root / 'scripts/fixtures/turn/cleanup_test.go').read_text(encoding='utf-8'), encoding='utf-8')
