"""Replay iOS logout with a delayed Network Extension stop."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "Silent/ViewModels/MainViewModel.swift").read_text(encoding="utf-8")
start = source.index("    func logout() {")
logout = source[start:source.index("    func toggleVPN() async", start)]

fixture = r'''
import Foundation

enum State { case connected, disconnecting, disconnected }
enum Payment { case idle }
enum Menu { case root }
enum ServerCatalog { static let fixedList: [String] = [] }
enum KeychainHelper { static func delete(_ key: String) {} }

@MainActor final class VM {
    final class VPN {
        var state = State.connected
        var stopSucceeds = true
        var stopGate: CheckedContinuation<Void, Never>?
        var stopCount = 0

        func disconnect() async -> Bool {
            stopCount += 1
            await withCheckedContinuation { stopGate = $0 }
            state = stopSucceeds ? .disconnected : .disconnecting
            return stopSucceeds
        }
    }

    final class API {
        var accessToken: String? = "fixture"
        var isLoggedIn: Bool { accessToken != nil }
        var serverLogoutOn: State?
        let vpn: VPN
        init(_ vpn: VPN) { self.vpn = vpn }
        func logout() { accessToken = nil }
        func logoutSession(access: String) async { serverLogoutOn = vpn.state }
    }

    let vpn = VPN()
    lazy var api = API(vpn)
    var vpnState = State.connected
    var loggedIn = true
    var savedAccountPending = false
    var vpnActionInProgress = false
    var canLogout: Bool { !vpnActionInProgress }
    var tunnelRecovery, prefetchTask, siteRoutingUpdate, logoutTask: Task<Void, Never>?
    var canRecoverTunnel = true
    var errorMessage: String?
    var serverConfigCache: Int? = 1
    let serverConfigCacheKey = "fixture"
    var sessionsVersion = 0, serverSelectionVersion = 0
    var bootstrapAttempted = true, bootstrapActive = true, bootstrapFailed = true
    var bootstrapExpired = false
    var bootstrapReconnecting = false, bootstrapMailReady = false
    var bootstrapDeadline: Date?
    var profile: Int? = 1
    var servers: [String] = []
    var serverHint = ""
    var connectedAt: Date?
    var menuOpen = true
    var menuPage = Menu.root
    var payment = Payment.idle
    var russianListReceived = true
    var log = ["old VPN"]
    var logResets = 0
    var bootstrapConfigured = true

    func beginVPNLogSession() {
        logResets += 1
        log.removeAll()
    }

    func startBootstrap(registrationRouting: Bool = false, reportFailure: Bool = true,
                        reuseLogSession: Bool = false) async {
        guard bootstrapConfigured, !bootstrapActive, !bootstrapAttempted else { return }
        precondition(vpn.state == .disconnected && !api.isLoggedIn)
        if !reuseLogSession { beginVPNLogSession() }
        log.append("temporary VPN")
    }

    LOGOUT
}

@main struct LogoutTest {
    @MainActor static func main() async {
        let vm = VM()
        vm.logout()
        guard vm.loggedIn, vm.api.isLoggedIn else {
            print("FAIL: account was cleared before iOS confirmed the VPN stop")
            exit(1)
        }
        while vm.vpn.stopGate == nil { await Task.yield() }
        precondition(vm.log == ["old VPN"] && vm.api.serverLogoutOn == nil)
        vm.logout()
        vm.vpn.stopGate?.resume()
        await vm.logoutTask?.value
        precondition(vm.vpn.stopCount == 1 && !vm.loggedIn && !vm.api.isLoggedIn)
        precondition(vm.api.serverLogoutOn == .disconnected)
        precondition(vm.log == ["temporary VPN"] && vm.logResets == 1 && vm.canLogout)

        let retry = VM()
        retry.vpn.stopSucceeds = false
        retry.logout()
        while retry.vpn.stopGate == nil { await Task.yield() }
        retry.vpn.stopGate?.resume()
        await retry.logoutTask?.value
        precondition(retry.loggedIn && retry.api.isLoggedIn && retry.canLogout)
        precondition(retry.log == ["old VPN"] && retry.errorMessage != nil)
        precondition(retry.api.serverLogoutOn == nil)
        retry.vpn.stopGate = nil
        retry.vpn.stopSucceeds = true
        retry.bootstrapConfigured = false
        retry.logout()
        while retry.vpn.stopGate == nil { await Task.yield() }
        retry.vpn.stopGate?.resume()
        await retry.logoutTask?.value
        precondition(!retry.loggedIn && retry.log.isEmpty && retry.logResets == 1)
        print("PASS: stop precedes logout, old log is cleared once, failed stop can be retried")
    }
}
'''

with tempfile.TemporaryDirectory(prefix="silent-logout-") as directory:
    path = Path(directory)
    swift = path / "Logout.swift"
    swift.write_text(fixture.replace("    LOGOUT", logout), encoding="utf-8")
    binary = path / "logout-test"
    subprocess.run(["swiftc", "-parse-as-library", str(swift), "-o", str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)
