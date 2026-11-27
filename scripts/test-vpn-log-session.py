"""Exercise session boundaries and run the production journal against two writers."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
vm = (root / "Silent/ViewModels/MainViewModel.swift").read_text(encoding="utf-8")
manager = (root / "Silent/Services/VpnManager.swift").read_text(encoding="utf-8")
provider = (root / "SilentTunnel/PacketTunnelProvider.swift").read_text(encoding="utf-8")
panel = (root / "Silent/Views/ConnectionFeedback.swift").read_text(encoding="utf-8")


def between(source, start, end):
    return source.split(start, 1)[1].split(end, 1)[0]


bootstrap = between(vm, "private func startBootstrap(", "private func connectBootstrap(")
toggle = between(vm, "func toggleVPN() async", "private func fetchMainConfig(")
login = between(vm, "func login(", "func register(")
register = between(vm, "func register(", "func dismissRegistrationConfirmation(")
auth = between(vm, "private func beginAuthLogIfNeeded(", "func clearVPNLog(")
saved = between(vm, "private func restoreSavedAccount(", "private func loadAccount(")
payment = between(vm, "private func preparePaymentRoute(", "private func selectPaymentAPI(")
restore = between(vm, "private func finishPaymentTunnel(", "func preparePayment(")
recovery = between(vm, "private func recoverAfterDisconnect(", "private func logConnection(")

assert bootstrap.index("beginVPNLogSession()") < bootstrap.index("connectBootstrap(local)")
assert toggle.index('logConnection("VPN отключён")') < toggle.index("beginVPNLogSession()") < toggle.index("vpn.connect(tunnel)")
assert "beginAuthLogIfNeeded()" in login and "beginAuthLogIfNeeded()" in register
assert "if vpn.state == .disconnected" in auth
assert "if quickPublicAttempt, vpn.state == .disconnected" in saved
assert saved.index("beginVPNLogSession()") < saved.index("api.probeSavedProfile()")
assert payment.index("beginVPNLogSession()") < payment.index("let picked")
assert restore.index("beginVPNLogSession()") < restore.index("vpn.connect(config)")
assert "beginVPNLogSession()" not in recovery
assert "startVPNTunnel(options: options)" in manager and "suppliedSession ?? VPNLog.beginSession()" in provider
assert "tunnelSnapshot.sessionID == currentSession" in panel

fixture = r'''
import Foundation

enum AppIdentity {
    static var groupURL: URL? {
        ProcessInfo.processInfo.environment["SILENT_TEST_LOG_DIR"].map {
            URL(fileURLWithPath: $0, isDirectory: true)
        }
    }
}

@main struct JournalTest {
    static func main() throws {
        let args = CommandLine.arguments
        if args.count > 1 {
            let id = UUID(uuidString: args[1])!
            while VPNLog.currentSessionID() == id { Thread.sleep(forTimeInterval: 0.001) }
            for _ in 0..<120 { VPNLog.write("old provider callback", sessionID: id) }
            return
        }
        VPNLog.write("legacy", sessionID: nil)
        precondition(VPNLog.read().entries.map(\.message) == ["legacy"])
        let first = VPNLog.beginSession()!
        VPNLog.write("main first", sessionID: first)
        precondition(VPNLog.read().entries.map(\.message) == ["main first"])

        let child = Process()
        child.executableURL = URL(fileURLWithPath: args[0])
        child.arguments = [first.uuidString]
        try child.run()
        for phase in ["bootstrap", "main again", "payment", "restored main", "direct login"] {
            let current = VPNLog.beginSession()!
            precondition(VPNLog.read().sessionID == current && VPNLog.read().entries.isEmpty)
            VPNLog.write("late first", sessionID: first)
            VPNLog.write(phase, sessionID: current)
            VPNLog.write(phase, sessionID: current)
            let rows = VPNLogRow.grouped(VPNLog.read().entries)
            precondition(rows.count == 1 && rows[0].entry.message == phase && rows[0].count == 2)
            VPNLog.clear()
            precondition(VPNLog.read().sessionID == current && VPNLog.read().entries.isEmpty)
            VPNLog.write("continued", sessionID: current)
            precondition(VPNLog.read().entries.map(\.message) == ["continued"])
        }
        child.waitUntilExit()
        precondition(child.terminationStatus == 0)
        precondition(VPNLog.read().entries.map(\.message) == ["continued"])
        print("PASS: fresh sessions, late writes across processes, grouping, and manual clear")
    }
}
'''
with tempfile.TemporaryDirectory(prefix="silent-vpn-log-") as directory:
    path = Path(directory)
    source = path / "Fixture.swift"
    source.write_text(fixture, encoding="utf-8")
    executable = path / "journal-test"
    subprocess.run(["swiftc", "-parse-as-library", str(root / "Shared/VPNLog.swift"),
                    str(source), "-o", str(executable)], check=True, timeout=60)
    subprocess.run([str(executable)], env={**os.environ, "SILENT_TEST_LOG_DIR": directory},
                   check=True, timeout=15)
