import Foundation
import Combine
import NetworkExtension
import UIKit

@MainActor
final class VpnManager: ObservableObject {
    static let shared = VpnManager()

    @Published var state: VpnState = .disconnected
    private(set) var sceneDiscardCount = 0
    private var waitForActiveScene = false
    private var pendingSceneStop: Task<Void, Never>?
    private let ownerSceneKey = "ios-vpn-owner-scene"
    private let sceneStopKey = "ios-vpn-discard-stop-pending"
    var closingDiscardedScene: Bool { waitForActiveScene }
    var onSceneDiscard: (() -> Void)?
    private var observer: NSObjectProtocol?
    private var pendingLaunchID: String?

    private init() {
        observer = NotificationCenter.default.addObserver(
            forName: .NEVPNStatusDidChange,
            object: nil,
            queue: .main
        ) { [weak self] note in
            guard let conn = note.object as? NEVPNConnection else { return }
            Task { @MainActor in
                guard let self, self.manager?.connection === conn else { return }
                if conn.status == .connected, let launchID = self.pendingLaunchID,
                   !AppIdentity.tunnelReady(for: launchID) {
                    self.state = .connecting
                } else {
                    self.state = Self.map(conn.status)
                }
            }
        }
    }

    private var manager: NETunnelProviderManager?

    var connectionIdentity: String? {
        guard state == .connected, let date = manager?.connection.connectedDate,
              let config = AppIdentity.readTunnelConfig() else { return nil }
        return "\(date.timeIntervalSinceReferenceDate)|\(config.serverIP)"
    }

    func refresh() async {
        guard let mgr = try? await load() else { return }
        state = Self.map(mgr.connection.status)
    }

    func isApiTunnelActive() async -> Bool {
        guard !UserDefaults.standard.bool(forKey: sceneStopKey) else { return false }
        guard let mgr = try? await load() else { return false }
        return mgr.connection.status == .connected
    }

    func connect(_ config: TunnelConfig, timeout: TimeInterval? = nil) async throws {
        VPNLog.write(AppIdentity.buildDescription, source: "Приложение", key: "app-build")
        let discardCount = sceneDiscardCount
        await pendingSceneStop?.value
        guard discardCount == sceneDiscardCount,
              !UserDefaults.standard.bool(forKey: sceneStopKey),
              !waitForActiveScene || UIApplication.shared.applicationState == .active else { throw CancellationError() }
        waitForActiveScene = false
        guard let url = AppIdentity.configURL else {
            throw APIError.server("Приложение не может передать настройки расширению VPN")
        }
        let mgr = try await load()
        guard mgr.connection.status == .disconnected || mgr.connection.status == .invalid else {
            throw APIError.server("Дождитесь отключения предыдущего VPN-соединения")
        }
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent().appendingPathComponent("engine"),
            withIntermediateDirectories: true
        )
        if let errURL = AppIdentity.errorURL { try? FileManager.default.removeItem(at: errURL) }
        let launchID = UUID().uuidString
        var launchConfig = config
        launchConfig.launchID = launchID
        let data = try JSONEncoder().encode(launchConfig)
        try data.write(to: url, options: .atomic)

        let proto = NETunnelProviderProtocol()
        proto.providerBundleIdentifier = AppIdentity.tunnelBundleId
        proto.serverAddress = config.serverIP
        proto.disconnectOnSleep = false
        // The provider selects full or API-only routes for checkout. Enforced
        // routing is reserved for the registration/Mail tunnel.
        proto.enforceRoutes = config.registrationRouting == true
        mgr.protocolConfiguration = proto
        mgr.localizedDescription = "Silent VPN"
        mgr.isEnabled = true
        try await mgr.saveToPreferences()
        try await mgr.loadFromPreferences()
        try Task.checkCancellation()
        guard discardCount == sceneDiscardCount else { throw CancellationError() }
        state = .connecting
        pendingLaunchID = launchID
        defer { pendingLaunchID = nil }
        do {
            try Task.checkCancellation()
            try mgr.connection.startVPNTunnel()
            let defaultTimeout: TimeInterval = config.hashes.count > 1 ? 58 : 50
            try await waitForConnection(mgr.connection, launchID: launchID, timeout: timeout ?? defaultTimeout)
        } catch {
            mgr.connection.stopVPNTunnel()
            state = Self.map(mgr.connection.status)
            throw error
        }
    }

    func sceneSessionsDiscarded(_ ids: Set<String>) {
        guard !ids.isEmpty else { return }
        if let owner = UserDefaults.standard.string(forKey: ownerSceneKey), !ids.contains(owner) { return }
        stopAfterSceneDiscard()
    }

    func prepareForegroundScene() async {
        let app = UIApplication.shared
        let defaults = UserDefaults.standard
        let owner = defaults.string(forKey: ownerSceneKey)
        let open = Set(app.openSessions.map(\.persistentIdentifier))
        if let activeScene = app.connectedScenes.first(where: { $0.activationState == .foregroundActive }) {
            let ownerDiscarded = owner.map { VPNSceneOwnership.wasDiscarded($0, openSessions: open) } ?? false
            if ownerDiscarded && pendingSceneStop == nil { stopAfterSceneDiscard() }
            if owner == nil || ownerDiscarded {
                defaults.set(activeScene.session.persistentIdentifier, forKey: ownerSceneKey)
            }
        }
        if defaults.bool(forKey: sceneStopKey), pendingSceneStop == nil { stopAfterSceneDiscard() }
        await pendingSceneStop?.value
    }

    private func stopAfterSceneDiscard() {
        sceneDiscardCount += 1
        waitForActiveScene = true
        UserDefaults.standard.set(true, forKey: sceneStopKey)
        onSceneDiscard?()
        // iOS may terminate the UI process immediately after this callback.
        if let connection = manager?.connection,
           connection.status != .disconnected && connection.status != .invalid {
            connection.stopVPNTunnel()
        }
        pendingSceneStop?.cancel()
        let discardCount = sceneDiscardCount
        pendingSceneStop = Task { [weak self] in
            guard let self else { return }
            defer {
                if self.sceneDiscardCount == discardCount { self.pendingSceneStop = nil }
            }
            guard (try? await self.load()) != nil, !Task.isCancelled else { return }
            await self.disconnect()
            if self.sceneDiscardCount == discardCount, self.state == .disconnected {
                UserDefaults.standard.removeObject(forKey: self.sceneStopKey)
            }
        }
    }

    private func waitForConnection(_ connection: NEVPNConnection, launchID: String, timeout: TimeInterval) async throws {
        let deadline = ProcessInfo.processInfo.systemUptime + timeout
        repeat {
            try await Task.sleep(nanoseconds: 250_000_000)
            switch connection.status {
            case .connected:
                guard AppIdentity.tunnelReady(for: launchID) else { continue }
                state = .connected
                return
            case .disconnected, .invalid:
                throw APIError.server(readError() ?? "VPN не запустился. Проверьте разрешение iOS и попробуйте ещё раз.")
            default:
                break
            }
        } while ProcessInfo.processInfo.systemUptime < deadline
        throw APIError.server("Не удалось подключиться к VPN за \(Int(timeout)) секунд")
    }

    func receivedPolicyRevision() async -> String? {
        guard let mgr = try? await load(), mgr.connection.status == .connected,
              let session = mgr.connection as? NETunnelProviderSession else { return nil }
        return await withCheckedContinuation { continuation in
            do {
                try session.sendProviderMessage(Data("policy-received".utf8)) { data in
                    continuation.resume(returning: data.flatMap { String(data: $0, encoding: .utf8) })
                }
            } catch { continuation.resume(returning: nil) }
        }
    }

    func enableRegistrationInternet() async -> Date? {
        guard let mgr = try? await load(), mgr.connection.status == .connected,
              let session = mgr.connection as? NETunnelProviderSession else { return nil }
        let deadline: Date? = await withCheckedContinuation { continuation in
            do {
                try session.sendProviderMessage(RegistrationTunnelRoute.request) { data in
                    let deadline = data.flatMap { try? JSONDecoder().decode(Date.self, from: $0) }
                    continuation.resume(returning: deadline)
                }
            } catch { continuation.resume(returning: nil) }
        }
        guard session.status == .connected, let deadline, deadline > Date() else { return nil }
        return deadline
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
        if connection.status != .disconnecting { connection.stopVPNTunnel() }
        for _ in 0..<20 {
            if connection.status == .disconnected || connection.status == .invalid { break }
            do { try await Task.sleep(nanoseconds: 250_000_000) } catch { break }
        }
        state = Self.map(connection.status)
    }

    func switchPaymentExit(to host: String) async throws -> Bool {
        let mgr = try await load()
        guard [.connected, .reasserting].contains(mgr.connection.status),
              AppIdentity.readTunnelConfig()?.paymentRouting == true,
              let session = mgr.connection as? NETunnelProviderSession else { throw APIError.network }
        let request = PaymentExitSwitch.Request(host: host)
        guard request.valid else { throw APIError.invalidURL }
        let data = try JSONEncoder().encode(request)
        let reply: PaymentExitSwitch.Reply? = try await withCheckedThrowingContinuation { continuation in
            do {
                try session.sendProviderMessage(data) { data in
                    continuation.resume(returning: data.flatMap { try? JSONDecoder().decode(PaymentExitSwitch.Reply.self, from: $0) })
                }
            } catch { continuation.resume(throwing: error) }
        }
        state = Self.map(session.status)
        guard let reply else { return false } // An extension from the previous installed build.
        guard reply.success else { throw APIError.server(reply.error ?? "Не удалось переключить временный маршрут") }
        // The provider may have just cleared reasserting before its reply.
        state = .connected
        return true
    }

    func updateSiteRouting(rules: [String], whitelist: Bool, russianEnabled: Bool) async throws {
        let mgr = try await load()
        guard mgr.connection.status == .connected, let session = mgr.connection as? NETunnelProviderSession,
              let url = AppIdentity.configURL, var config = AppIdentity.readTunnelConfig(),
              config.bootstrapDuration == nil else { return }
        try Task.checkCancellation()
        let previous = config
        config.excludeCIDRs = rules
        config.sitesWhitelist = whitelist
        config.russian = RussianServices.policy(enabled: russianEnabled)
        let data = try JSONEncoder().encode(config)
        try data.write(to: url, options: .atomic)
        do {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                do {
                    try session.sendProviderMessage(Data("site-routing".utf8)) { reply in
                        if reply == Data("ok".utf8) { continuation.resume() }
                        else { continuation.resume(throwing: APIError.server("Не удалось применить маршруты сайтов")) }
                    }
                } catch { continuation.resume(throwing: error) }
            }
        } catch {
            if (try? Data(contentsOf: url)) == data {
                try? JSONEncoder().encode(previous).write(to: url, options: .atomic)
            }
            throw error
        }
    }

    func readError() -> String? {
        guard let url = AppIdentity.errorURL, let text = try? String(contentsOf: url, encoding: .utf8) else { return nil }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    func lastDisconnectError() async -> NSError? {
        guard let manager, manager.connection.status == .disconnected else { return nil }
        do {
            try await manager.connection.fetchLastDisconnectError()
            return nil
        } catch {
            return error as NSError
        }
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
        case .connecting: return .connecting
        case .reasserting: return .reconnecting
        case .disconnecting: return .disconnecting
        default: return .disconnected
        }
    }
}
