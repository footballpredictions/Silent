import Foundation
import NetworkExtension

@MainActor
final class VpnManager: ObservableObject {
    static let shared = VpnManager()

    @Published var state: VpnState = .disconnected
    private var observer: NSObjectProtocol?

    private init() {
        observer = NotificationCenter.default.addObserver(
            forName: .NEVPNStatusDidChange,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let conn = note.object as? NEVPNConnection else { return }
            Task { @MainActor in
                self?.state = Self.map(conn.status)
            }
        }
    }

    func refresh() async {
        guard let mgr = try? await load() else { return }
        state = Self.map(mgr.connection.status)
    }

    func connect(_ config: TunnelConfig) async throws {
        guard let url = AppIdentity.configURL else {
            throw APIError.server("Нет App Group. Включите group.com.silent.vpn в подписи приложения и расширения.")
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent().appendingPathComponent("engine"),
            withIntermediateDirectories: true
        )
        if let errURL = AppIdentity.errorURL { try? FileManager.default.removeItem(at: errURL) }
        let data = try JSONEncoder().encode(config)
        try data.write(to: url, options: .atomic)

        let mgr = try await load()
        let proto = NETunnelProviderProtocol()
        proto.providerBundleIdentifier = AppIdentity.tunnelBundleId
        proto.serverAddress = config.serverIP
        proto.disconnectOnSleep = false
        mgr.protocolConfiguration = proto
        mgr.localizedDescription = "Silent VPN"
        mgr.isEnabled = true
        try await mgr.saveToPreferences()
        try await mgr.loadFromPreferences()
        state = .connecting
        try mgr.connection.startVPNTunnel()
    }

    func disconnect() async {
        guard let mgr = try? await load() else {
            state = .disconnected
            return
        }
        state = .disconnecting
        mgr.connection.stopVPNTunnel()
    }

    func updateSiteRouting(rules: [String], whitelist: Bool, russian: RussianRoutingPolicy?) async throws {
        let mgr = try await load()
        guard mgr.connection.status == .connected || mgr.connection.status == .reasserting,
              let session = mgr.connection as? NETunnelProviderSession,
              let url = AppIdentity.configURL else { return }
        var config = try JSONDecoder().decode(TunnelConfig.self, from: Data(contentsOf: url))
        config.excludeCIDRs = rules
        config.sitesWhitelist = whitelist
        config.russian = russian
        try JSONEncoder().encode(config).write(to: url, options: .atomic)
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            do {
                try session.sendProviderMessage(Data("site-routing".utf8)) { reply in
                    if reply == Data("ok".utf8) { continuation.resume() }
                    else { continuation.resume(throwing: APIError.server("Не удалось применить маршруты сайтов")) }
                }
            } catch { continuation.resume(throwing: error) }
        }
    }

    func readError() -> String? {
        guard let url = AppIdentity.errorURL, let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private func load() async throws -> NETunnelProviderManager {
        let all = try await NETunnelProviderManager.loadAllFromPreferences()
        if let existing = all.first(where: {
            ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == AppIdentity.tunnelBundleId
        }) ?? all.first {
            return existing
        }
        return NETunnelProviderManager()
    }

    private static func map(_ status: NEVPNStatus) -> VpnState {
        switch status {
        case .connected: return .connected
        case .connecting, .reasserting: return .connecting
        case .disconnecting: return .disconnecting
        default: return .disconnected
        }
    }
}
