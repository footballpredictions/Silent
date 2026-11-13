import Foundation
import Combine
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
                guard let self, self.manager?.connection === conn else { return }
                self.state = Self.map(conn.status)
            }
        }
    }

    private var manager: NETunnelProviderManager?

    func refresh() async {
        guard let mgr = try? await load() else { return }
        state = Self.map(mgr.connection.status)
    }

    func isApiTunnelActive() async -> Bool {
        guard let mgr = try? await load() else { return false }
        return mgr.connection.status == .connected
    }

    func connect(_ config: TunnelConfig) async throws {
        guard let url = AppIdentity.configURL else {
            throw APIError.server("Приложение не может передать настройки расширению VPN")
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent().appendingPathComponent("engine"),
            withIntermediateDirectories: true
        )
        if let errURL = AppIdentity.errorURL { try? FileManager.default.removeItem(at: errURL) }
        let data = try JSONEncoder().encode(config)
        try data.write(to: url, options: .atomic)

        let mgr = try await load()
        guard mgr.connection.status == .disconnected || mgr.connection.status == .invalid else {
            throw APIError.server("Дождитесь отключения предыдущего VPN-соединения")
        }
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
        do {
            try mgr.connection.startVPNTunnel()
            try await waitForConnection(mgr.connection)
        } catch {
            mgr.connection.stopVPNTunnel()
            state = Self.map(mgr.connection.status)
            throw error
        }
    }

    private func waitForConnection(_ connection: NEVPNConnection) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + 50
        repeat {
            try await Task.sleep(nanoseconds: 250_000_000)
            switch connection.status {
            case .connected:
                state = .connected
                return
            case .disconnected, .invalid:
                throw APIError.server(readError() ?? "VPN не запустился. Проверьте разрешение iOS и попробуйте ещё раз.")
            default:
                break
            }
        } while ProcessInfo.processInfo.systemUptime < deadline
        throw APIError.server("Не удалось подключиться к VPN за 50 секунд")
    }

    func disconnect() async {
        guard let mgr = try? await load() else {
            state = .disconnected
            return
        }
        let connection = mgr.connection
        guard connection.status != .invalid, connection.status != .disconnected else {
            state = .disconnected
            return
        }
        state = .disconnecting
        connection.stopVPNTunnel()
        for _ in 0..<20 {
            if connection.status == .disconnected || connection.status == .invalid { break }
            do { try await Task.sleep(nanoseconds: 250_000_000) } catch { break }
        }
        state = Self.map(connection.status)
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
        if let manager { return manager }
        let all = try await NETunnelProviderManager.loadAllFromPreferences()
        let own = all.first(where: {
            ($0.protocolConfiguration as? NETunnelProviderProtocol)?.providerBundleIdentifier == AppIdentity.tunnelBundleId
        }) ?? NETunnelProviderManager()
        if let manager { return manager }
        manager = own
        return own
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
