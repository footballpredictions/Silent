import Foundation

enum AppIdentity {
    static let appGroup = "group.io.github.silentvpn3.silentvpn"
    static let tunnelBundleId = "io.github.silentvpn3.silentvpn.tunnel"
    static let configName = "tunnel-config.json"
    static let errorName = "tunnel-error.txt"

    static var groupURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
    }

    static var configURL: URL? { groupURL?.appendingPathComponent(configName) }
    static var errorURL: URL? { groupURL?.appendingPathComponent(errorName) }
    static var workURL: URL? { groupURL?.appendingPathComponent("engine", isDirectory: true) }

    static func readTunnelConfig() -> TunnelConfig? {
        guard let configURL, let data = try? Data(contentsOf: configURL) else { return nil }
        return try? JSONDecoder().decode(TunnelConfig.self, from: data)
    }
}

enum RegistrationTunnelRoute {
    static let request = Data("registration-routing".utf8)
    static let internetDNS = ["1.1.1.1", "9.9.9.9"]
    static let duration = 120

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
    var registrationRouting: Bool? = nil

    var bootstrapRoutesInternet: Bool { paymentRouting == true || registrationRouting == true }
}
