import Foundation

enum AppIdentity {
    static let appGroup = "group.io.github.silentvpn3.silentvpn"
    static let tunnelBundleId = "io.github.silentvpn3.silentvpn.tunnel"
    static let configName = "tunnel-config.json"
    static let errorName = "tunnel-error.txt"

    static var buildDescription: String {
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "?"
        let revision = Bundle.main.object(forInfoDictionaryKey: "SilentBuildRevision") as? String ?? "unknown"
        return "Сборка \(build) · код \(revision.prefix(12))"
    }

    static var groupURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
    }

    static var configURL: URL? { groupURL?.appendingPathComponent(configName) }
    static var errorURL: URL? { groupURL?.appendingPathComponent(errorName) }
    static var readyURL: URL? { groupURL?.appendingPathComponent("tunnel-ready.txt") }
    static var workURL: URL? { groupURL?.appendingPathComponent("engine", isDirectory: true) }

    static func readTunnelConfig() -> TunnelConfig? {
        guard let configURL, let data = try? Data(contentsOf: configURL) else { return nil }
        return try? JSONDecoder().decode(TunnelConfig.self, from: data)
    }

    // Each start has its own nonce. A ready receipt from the preceding
    // bootstrap/main extension must never confirm a newly started tunnel.
    static func tunnelReady(for launchID: String, at url: URL? = readyURL) -> Bool {
        guard !launchID.isEmpty, let url, let data = try? Data(contentsOf: url) else { return false }
        return data == Data(launchID.utf8)
    }

    static func markTunnelReady(for launchID: String?, at url: URL? = readyURL) throws {
        guard let launchID else { return } // Keep older stored configs readable.
        guard let url else { throw CocoaError(.fileNoSuchFile) }
        try Data(launchID.utf8).write(to: url, options: .atomic)
    }
}

enum VPNSceneOwnership {
    static func wasDiscarded(_ ownerID: String, openSessions: Set<String>) -> Bool {
        !openSessions.contains(ownerID)
    }
}

enum PaymentExitSwitch {
    static let hosts = ["87.58.213.193", "78.17.74.27", "89.37.192.241", "89.125.188.100"]
    struct Request: Codable {
        let command: String
        let host: String
        init(host: String) { command = "payment-exit"; self.host = host }
        var valid: Bool { command == "payment-exit" && PaymentExitSwitch.hosts.contains(host) }
    }
    struct Reply: Codable {
        let success: Bool
        let error: String?
    }
}

enum RegistrationTunnelRoute {
    static let request = Data("registration-routing".utf8)
    static let internetDNS = ["1.1.1.1", "9.9.9.9"]
    static let duration = 120
    static let expiredMessage = "Время временного VPN истекло"

    static func enable(on active: TunnelConfig) -> TunnelConfig? {
        guard let currentDuration = active.bootstrapDuration, (1...duration).contains(currentDuration),
              active.paymentRouting != true,
              active.deviceId.hasPrefix("boot:") else { return nil }
        var config = active
        config.registrationRouting = true
        config.dns = internetDNS
        config.bootstrapDuration = duration
        return config
    }
}

struct TunnelConfig: Codable {
    var deviceId: String
    var serverIP: String
    var serverPort: Int
    var password: String
    var hashes: [String]
    var workers: Int
    var address: String
    var dns: [String]
    var mtu: Int
    var excludeCIDRs: [String]
    var sitesWhitelist: Bool? = nil
    var russian: RussianRoutingPolicy? = nil
    var bootstrapDuration: Int? = nil
    var paymentRouting: Bool? = nil
    var paymentAPIOnly: Bool? = nil
    var registrationRouting: Bool? = nil
    var launchID: String? = nil

    var bootstrapRoutesInternet: Bool {
        registrationRouting == true || (paymentRouting == true && paymentAPIOnly != true)
    }
}
