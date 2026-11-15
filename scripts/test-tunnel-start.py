"""Execute VpnManager's actual startup wait with an early iOS connected status."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'Silent/Services/VpnManager.swift').read_text(encoding='utf-8')
start = source.index('    private func waitForConnection(')
opening = source.index('{', start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
method = source[start:end].replace('private func', 'func', 1)
arguments = 'connection, launchID: "main-launch", timeout: 2' if 'launchID:' in method.split('{', 1)[0] else 'connection, timeout: 2'
prefix = '''import Foundation
enum NEVPNStatus { case connected, disconnected, invalid, connecting }
final class NEVPNConnection { var status: NEVPNStatus = .connected }
enum VpnState { case connected, disconnected }
enum APIError: Error { case server(String) }
@MainActor enum AppIdentity {
    static var readyID = "bootstrap-launch"
    static func tunnelReady(for launchID: String) -> Bool { readyID == launchID }
}
@MainActor final class StartupFixture {
    var state = VpnState.disconnected
    func readError() -> String? { nil }
'''
suffix = '''
}
@main struct StartupTest {
    @MainActor static func main() async throws {
        let connection = NEVPNConnection()
        let fixture = StartupFixture()
        let readyTask = Task {
            try await Task.sleep(nanoseconds: 600_000_000)
            AppIdentity.readyID = "main-launch"
        }
        let started = ProcessInfo.processInfo.systemUptime
        try await fixture.waitForConnection(ARGS)
        guard AppIdentity.readyID == "main-launch", ProcessInfo.processInfo.systemUptime - started >= 0.6 else {
            print("FAIL: iOS connected status started HTTP validation before the new WireGuard handshake; bootstrap readiness must not confirm the main tunnel")
            exit(1)
        }
        try await readyTask.value
        print("PASS: main startup waits for the matching WireGuard-ready launch")
        AppIdentity.readyID = "bootstrap-launch"
        let cancelled = Task { try await fixture.waitForConnection(ARGS) }
        cancelled.cancel()
        do { try await cancelled.value; print("FAIL: startup ignored cancellation"); exit(1) }
        catch is CancellationError {}
        print("PASS: cancellation stops the startup wait")
    }
}
'''.replace('ARGS', arguments)
with tempfile.TemporaryDirectory(prefix='silent-startup-') as directory:
    path = Path(directory)
    swift = path / 'Startup.swift'
    swift.write_text(prefix + method + suffix, encoding='utf-8')
    binary = path / 'startup-test'
    compiler = shutil.which('swiftc')
    if not compiler:
        raise SystemExit('swiftc is required; this regression runs on the macOS build runner')
    subprocess.run([compiler, '-parse-as-library', str(swift), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)
