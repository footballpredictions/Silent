"""Replay the actual iOS payment flow and Network Extension route settings."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(os.environ.get('PAYMENT_TEST_SOURCE', Path(__file__).resolve().parents[1]))


def read(path):
    return (root / path).read_text(encoding='utf8')


def extract(text, declaration):
    start = text.index(declaration)
    opening = text.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


vm = read('Silent/ViewModels/MainViewModel.swift')
shared = read('Shared/AppIdentity.swift')
provider = read('SilentTunnel/PacketTunnelProvider.swift')
fixture = r'''
import Foundation
struct RussianRoutingPolicy: Codable { let enabled: Bool }
enum VpnState { case connected, disconnected, connecting, reconnecting, disconnecting }
enum APIError: Error { case network, invalidURL, http(Int, String), server(String) }
struct PaymentPreview { let plan: String }
struct PaymentMainSnapshot: Codable { let account: String; let config: TunnelConfig }
struct Profile { let id = "fixture" }
enum KeychainHelper { static func set(_ value: String, key: String) {} }
enum PublicApiFailover {
    static let tunnelAPI = "http://10.66.66.1:8000"
    static let paymentPublicBases = ["https://public.fixture.invalid"]
}
@MainActor enum AppIdentity {
    static var config: TunnelConfig?
    static func readTunnelConfig() -> TunnelConfig? { config }
}
@MainActor final class VPN {
    var state = VpnState.disconnected
    var starts = [TunnelConfig]()
    var exits = [String]()
    func disconnect() async { state = .disconnected }
    func connect(_ config: TunnelConfig, timeout: TimeInterval) async throws {
        starts.append(config); AppIdentity.config = config; state = .connected
    }
    func switchPaymentExit(to host: String) async throws -> Bool {
        exits.append(host); AppIdentity.config?.serverIP = host; return true
    }
}
@MainActor enum PaymentConnectivity {
    static var onCheck: (() -> Bool)?
    static func check(host: String) async -> Bool { onCheck?() ?? false }
}
@MainActor final class API {
    let deviceFingerprint = "fixture"
    var failFirstGateway = false
    func checkTunnelGateway(timeout: TimeInterval) async throws {
        if failFirstGateway && AppIdentity.config?.serverIP == BootstrapLaunch.paymentHosts[0] {
            throw APIError.network
        }
    }
    func previewPayment(plan: String, base: String) async throws -> PaymentPreview {
        guard base == PublicApiFailover.tunnelAPI else { throw APIError.network }
        return PaymentPreview(plan: plan)
    }
}
struct NEIPv4Route {
    let destinationAddress: String; let subnetMask: String
    static func `default`() -> Self { Self(destinationAddress: "0.0.0.0", subnetMask: "0.0.0.0") }
}
struct NEIPv6Route { static func `default`() -> Self { Self() } }
final class NEIPv4Settings {
    var includedRoutes: [NEIPv4Route]?; var excludedRoutes: [NEIPv4Route]?
    init(addresses: [String], subnetMasks: [String]) {}
}
final class NEIPv6Settings {
    var includedRoutes: [NEIPv6Route]?
    init(addresses: [String], networkPrefixLengths: [NSNumber]) {}
}
final class NEDNSSettings { var matchDomains: [String]?; init(servers: [String]) {} }
final class NEPacketTunnelNetworkSettings {
    var ipv4Settings: NEIPv4Settings?; var ipv6Settings: NEIPv6Settings?; var dnsSettings: NEDNSSettings?
    var mtu: NSNumber?; init(tunnelRemoteAddress: String) {}
}
final class Provider {
    func parseAddress(_ raw: String) -> (ip: String, mask: String) { ("10.66.66.2", "255.255.255.255") }
    func excludeRoutes(_ routes: [String]) -> [NEIPv4Route] { [] }
    REPLAY_SETTINGS
    func apiOnly(_ config: TunnelConfig) -> Bool {
        let settings = makeSettings(config)
        return settings.ipv4Settings?.includedRoutes?.map(\.destinationAddress) == ["10.66.66.1"] &&
            settings.ipv6Settings == nil && settings.dnsSettings == nil
    }
}
@MainActor final class VM {
    let api = API(); let vpn = VPN()
    let bootstrapHash = "test_fixture_call_hash"
    let bootstrapPassword = "fixture"
    let paymentRestoreKey = "fixture"
    var savedMainForPayment: TunnelConfig?
    var paymentTunnelActive = false
    var profile: Profile? = Profile()
    enum Level { case info, error, success }
    func logConnection(_ text: String, level: Level = .info) {}
    REPLAY_PREPARATION
    REPLAY_SELECTION
    func route() async throws -> String { try await preparePaymentRoute("monthly").base }
}
@main struct Replay {
    @MainActor static func main() async {
        let defaults = UserDefaults.standard
        let key = "payment-preferred-exit"
        var failures = [String]()
        func expect(_ value: Bool, _ message: String) { if !value { failures.append(message) } }
        for mainOn in [false, true] {
            defaults.set(BootstrapLaunch.paymentHosts[0], forKey: key)
            let vm = VM()
            let main = TunnelConfig(deviceId: "fixture", serverIP: "203.0.113.9", serverPort: 56000,
                                    password: "fixture", hashes: ["fixture"], workers: 1, address: "",
                                    dns: [], mtu: 1200, excludeCIDRs: [])
            AppIdentity.config = mainOn ? main : nil
            if mainOn { vm.vpn.state = .connected }
            PaymentConnectivity.onCheck = {
                vm.vpn.state == .disconnected || AppIdentity.config.map(Provider().apiOnly) == true
            }
            let result = try? await vm.route()
            expect(result == PublicApiFailover.tunnelAPI, "site direct + API only via VPN failed, mainOn=\(mainOn)")
            expect(vm.vpn.starts.count == 1 && vm.vpn.exits.isEmpty, "cycled a working API exit")
            expect(vm.savedMainForPayment?.serverIP == (mainOn ? main.serverIP : nil), "lost main VPN snapshot")
            expect(vm.vpn.starts.first.map(Provider().apiOnly) == true, "split mode included default route or DNS")
        }
        defaults.set(BootstrapLaunch.paymentHosts[0], forKey: key)
        let fallback = VM()
        AppIdentity.config = nil
        PaymentConnectivity.onCheck = { fallback.vpn.state == .connected }
        let fallbackResult = try? await fallback.route()
        expect(fallbackResult == PublicApiFailover.tunnelAPI, "working full payment route was lost")
        expect(fallback.vpn.starts.first.map(Provider().apiOnly) == false, "unverified direct route selected")
        defaults.set(BootstrapLaunch.paymentHosts[0], forKey: key)
        let switches = VM(); switches.api.failFirstGateway = true
        AppIdentity.config = nil
        PaymentConnectivity.onCheck = {
            switches.vpn.state == .disconnected || AppIdentity.config.map(Provider().apiOnly) == true
        }
        let switchedResult = try? await switches.route()
        expect(switchedResult == PublicApiFailover.tunnelAPI, "next gateway did not serve split checkout")
        expect(switches.vpn.starts.count == 1 && switches.vpn.exits == [BootstrapLaunch.paymentHosts[1]],
               "gateway failover restarted iOS VPN")
        expect(AppIdentity.config.map(Provider().apiOnly) == true, "exit switch changed split routing")
        defaults.set(BootstrapLaunch.paymentHosts[0], forKey: key)
        let lostDirect = VM()
        AppIdentity.config = nil
        PaymentConnectivity.onCheck = { lostDirect.vpn.state == .disconnected }
        let lostResult = try? await lostDirect.route()
        expect(lostResult == nil && lostDirect.vpn.starts.count == 1 && lostDirect.vpn.exits.isEmpty,
               "a lost direct browser route provoked VPN exit changes")
        if failures.isEmpty { print("PASS: split payment, VPN handoff, full fallback and in-place exit change") }
        else { failures.forEach { print("FAIL: \($0)") }; exit(1) }
    }
}
'''
fixture = fixture.replace('REPLAY_SETTINGS', extract(provider, '    private func makeSettings('))
fixture = fixture.replace('REPLAY_PREPARATION', extract(vm, '    private func preparePaymentRoute('))
fixture = fixture.replace('REPLAY_SELECTION', extract(vm, '    private func selectPaymentAPI('))
with tempfile.TemporaryDirectory(prefix='silent-payment-split-') as directory:
    source = Path(directory) / 'Replay.swift'
    binary = source.with_suffix('')
    source.write_text('\n'.join([shared[shared.index('enum PaymentExitSwitch'):],
                                read('Silent/Services/PaymentRoute.swift'),
                                read('Silent/Services/BootstrapLaunch.swift'), fixture]), encoding='utf8')
    subprocess.run(['swiftc', '-parse-as-library', str(source), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=15)
