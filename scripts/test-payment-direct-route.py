"""Replay the actual preflight without creating payments or starting a VPN.

The existing temporary-route fallback is a sentinel: selecting it while a direct
site and public API both work is the regression, not an external network test.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'Silent/ViewModels/MainViewModel.swift').read_text(encoding='utf-8')
start = source.index('    private func preparePaymentRoute(')
end = source.index('        try Task.checkCancellation()', start)
preflight = source[start:end] + '        throw FixtureError.temporaryFallback\n    }\n'
start = source.index('    private func selectPaymentAPI(')
opening = source.index('{', start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
selection = source[start:end]
fixture = r'''import Foundation
enum VpnState { case connected, disconnected }
enum FixtureError: Error { case temporaryFallback }
enum APIError: Error { case network, invalidURL, http(Int,String) }
struct PaymentPreview { let plan: String }
enum PublicApiFailover {
    static let tunnelAPI = "http://10.66.66.1:8000"
    static let paymentPublicBases = ["https://api.fixture.invalid", "https://api.fixture.invalid:2083"]
}
@MainActor final class VPN { var state = VpnState.disconnected }
@MainActor enum PaymentRoute {
    static var reachable = true
    static var onCheck: (() -> Void)?
    static func check() async -> Bool { onCheck?(); return reachable }
}
@MainActor final class API {
    var calls: [String] = []
    var unavailable: Set<String> = []
    var terminalError: APIError?
    var onPreview: (() -> Void)?
    func previewPayment(plan: String, base: String) async throws -> PaymentPreview {
        calls.append(base); onPreview?()
        if let terminalError { throw terminalError }
        if unavailable.contains(base) { throw APIError.network }
        return PaymentPreview(plan: plan)
    }
}
@MainActor final class VM {
    let vpn = VPN(); let api = API()
    var paymentTunnelActive = false
    enum Level { case success, info, error }
    func logConnection(_ text: String, level: Level = .info) {}
    func beginVPNLogSession() {}
PREFLIGHT
SELECTION
    func route() async throws -> String { try await preparePaymentRoute("monthly").base }
}
@main struct DirectPaymentReplay {
    @MainActor static func main() async throws {
        var failures: [String] = []
        func scenario(_ name: String, connected: Bool = false, reachable: Bool = true,
                      expected: String?, configure: (VM) -> Void = { _ in }) async {
            let vm = VM(); vm.vpn.state = connected ? .connected : .disconnected
            PaymentRoute.reachable = reachable; PaymentRoute.onCheck = nil
            configure(vm)
            do {
                let selected = try await vm.route()
                if selected != expected { failures.append(name + ": wrong API route " + selected) }
                else { print("PASS: " + name) }
            } catch FixtureError.temporaryFallback {
                if expected != nil { failures.append(name + ": unnecessary temporary VPN hides working direct payment") }
                else { print("PASS: " + name) }
            } catch { failures.append(name + ": unexpected error " + String(describing: error)) }
        }
        let primary = PublicApiFailover.paymentPublicBases[0]
        let alternate = PublicApiFailover.paymentPublicBases[1]
        await scenario("VPN-off direct YooMoney and API avoid temporary VPN", expected: primary)
        await scenario("working main VPN keeps its tunnel API", connected: true, expected: PublicApiFailover.tunnelAPI)
        await scenario("unreachable direct site retains temporary fallback", reachable: false, expected: nil) { vm in
            PaymentRoute.onCheck = { precondition(vm.api.calls.isEmpty) }
        }
        await scenario("direct API fallback stays on public HTTPS", expected: alternate) { $0.api.unavailable = [primary] }
        await scenario("site-only access does not pretend the API works", expected: nil) { $0.api.unavailable = [primary, alternate] }
        await scenario("disconnected held payment route retains owned tunnel cleanup", expected: nil) { $0.paymentTunnelActive = true }
        await scenario("network change during preflight rejects stale route", expected: nil) { vm in
            PaymentRoute.onCheck = { vm.vpn.state = .connected }
        }
        await scenario("network change during API preview rejects stale route", expected: nil) { vm in
            vm.api.onPreview = { vm.vpn.state = .connected }
        }
        let denied = VM(); denied.api.terminalError = .http(400,"invalid plan")
        PaymentRoute.reachable = true; PaymentRoute.onCheck = nil
        do { _ = try await denied.route(); failures.append("terminal API error was ignored") }
        catch APIError.http(400, _) { print("PASS: terminal API error is preserved") }
        catch { failures.append("terminal API error became route fallback") }
        if !failures.isEmpty { failures.forEach { print("FAIL: " + $0) }; exit(1) }
    }
}
'''.replace('PREFLIGHT', preflight).replace('SELECTION', selection)
with tempfile.TemporaryDirectory(prefix='silent-payment-direct-') as directory:
    target = Path(directory)
    swift = target / 'Direct.swift'
    binary = target / 'direct-payment'
    swift.write_text(fixture, encoding='utf-8')
    subprocess.run([shutil.which('swiftc') or 'swiftc', '-parse-as-library', str(swift), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)
