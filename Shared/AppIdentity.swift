import Foundation

enum AppIdentity {
    static let appGroup = "group.com.silent.vpn"
    static let tunnelBundleId = "com.silent.vpn.tunnel"
    static let configName = "tunnel-config.json"
    static let errorName = "tunnel-error.txt"

    static var groupURL: URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)
    }

    static var configURL: URL? { groupURL?.appendingPathComponent(configName) }
    static var errorURL: URL? { groupURL?.appendingPathComponent(errorName) }
    static var workURL: URL? { groupURL?.appendingPathComponent("engine", isDirectory: true) }
}

struct TunnelConfig: Codable {
    var deviceId: String
    var serverIP: String
    var serverPort: Int
    var password: String
    var hashes: [String]
    var workers: Int
    var privateKey: String
    var publicKey: String
    var address: String
    var dns: [String]
    var mtu: Int
    var excludeCIDRs: [String]
    var sitesWhitelist: Bool? = nil
    var russian: RussianRoutingPolicy? = nil
}
