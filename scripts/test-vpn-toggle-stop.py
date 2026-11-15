"""Exercise the actual manual-stop branch and API notification without iOS."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
vm = (root / 'Silent/ViewModels/MainViewModel.swift').read_text(encoding='utf-8')
start = vm.index('    func toggleVPN() async {')
branch = vm[start:vm.index('        guard hasAccess else {', start)] + '\n    }\n'
api = (root / 'Silent/Services/APIService.swift').read_text(encoding='utf-8')
start = api.index('    func disconnect() async throws {')
opening = api.index('{', start)
depth, end = 1, opening + 1
while depth:
    depth += (api[end] == '{') - (api[end] == '}')
    end += 1
notification = api[start:end]
prefix = '''import Foundation
enum VpnState { case connected, connecting, reconnecting, disconnecting, disconnected }
enum PublicApiFailover { static let tunnelAPI = "http://10.66.66.1:8000" }
@MainActor final class VpnManager {
    static let shared = VpnManager()
    var state = VpnState.connected
    func isApiTunnelActive() async -> Bool { state == .connected }
    func disconnect() async { state = .disconnected }
}
@MainActor final class APIService {
    let deviceFingerprint = "fixture"
    var notifiedOnLiveTunnel = false
    var notifications = 0
    func requestData<T:Encodable>(_ path:String, method:String, body:T) async throws -> Data {
        notifications += 1
        notifiedOnLiveTunnel = VpnManager.shared.state == .connected
        // Old fallback begins after VPN is stopped and holds the UI action.
        if !notifiedOnLiveTunnel { try await Task.sleep(nanoseconds: 200_000_000) }
        return Data()
    }
    func requestOnce<T:Encodable>(_ path:String, method:String, body:T, auth:Bool, base:String,
        allowRefresh:Bool, verifyTLS:Bool, timeout:TimeInterval) async throws -> Data {
        precondition(path == "api/vpn/disconnect" && base == PublicApiFailover.tunnelAPI)
        precondition(timeout <= 2 && !allowRefresh, "Stop must not enter public failover/token refresh")
        notifications += 1
        notifiedOnLiveTunnel = VpnManager.shared.state == .connected
        return Data()
    }
'''
middle = '''
}
@MainActor final class ToggleFixture {
    let vpn = VpnManager.shared
    let api = APIService()
    var loggedIn = true
    var vpnActionInProgress = false
    var paymentTunnelActive = false
    var paymentCleanupActive = false
    var paymentTask: Task<Void,Never>?
    var prefetchTask: Task<Void,Never>?
    var tunnelRecovery: Task<Void,Never>?
    var errorMessage:String?
    var vpnState = VpnState.connected
    var russianListReceived = true
    var connectedAt:Date? = Date()
    var canRecoverTunnel = true
    func logConnection(_ message:String) {}
'''
suffix = '''
}
@main struct StopTest {
    @MainActor static func main() async throws {
        let vm = ToggleFixture()
        let stop = Task { await vm.toggleVPN() }
        try await Task.sleep(nanoseconds: 50_000_000)
        guard !vm.vpnActionInProgress else {
            print("FAIL: VPN is already off but the main switch ignores taps while offline disconnect API fallback is pending")
            exit(1)
        }
        await stop.value
        guard vm.api.notifiedOnLiveTunnel, vm.api.notifications == 1, vm.vpnState == .disconnected else {
            print("FAIL: manual stop must report once through the live tunnel, then release the UI in the actual disconnected state")
            exit(1)
        }
        // A second stop cycle in the same app must not retain an action lock.
        vm.vpn.state = .connected
        vm.vpnState = .connected
        await vm.toggleVPN()
        guard !vm.vpnActionInProgress, vm.vpnState == .disconnected, vm.api.notifications == 2 else { exit(1) }
        print("PASS: repeated manual stop releases the switch and never notifies through an offline route")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='silent-toggle-stop-') as directory:
    path = Path(directory)
    source = path / 'Stop.swift'
    source.write_text(prefix + notification + middle + branch + suffix, encoding='utf-8')
    binary = path / 'stop-test'
    subprocess.run([shutil.which('swiftc') or 'swiftc', '-parse-as-library', str(source), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)
