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
}
