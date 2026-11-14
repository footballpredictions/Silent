import Foundation

struct ServerConfigCache: Codable {
    static let refreshInterval: TimeInterval = 900
    static let lifetime: TimeInterval = 24 * 60 * 60

    struct Entry: Codable {
        let savedAt: Date
        let config: VpnConfig
    }

    let account: String
    let fingerprint: String
    private(set) var slots: [String: Entry] = [:]

    func config(server: String, account: String, fingerprint: String, deviceId: String,
                maxAge: TimeInterval = Self.lifetime, now: Date = Date()) -> VpnConfig? {
        guard self.account == account, self.fingerprint == fingerprint, let entry = slots[server],
              entry.config.device_id == deviceId, entry.config.selected_server == server,
              entry.savedAt <= now, now.timeIntervalSince(entry.savedAt) < maxAge else { return nil }
        return entry.config
    }

    mutating func save(_ config: VpnConfig, for server: String, now: Date = Date()) {
        guard config.selected_server == server, !config.device_id.isEmpty, !config.device_id.hasPrefix("boot:"),
              !config.server_ip.isEmpty, (1...65535).contains(config.server_port),
              !config.wdtt_password.isEmpty, !config.vk_hashes.isEmpty else { return }
        // iOS obtains the actual WireGuard keys via GETCONF from the relay.
        var transport = config
        transport.wg_private_key = ""
        slots[server] = Entry(savedAt: now, config: transport)
    }

    mutating func remove(server: String) {
        slots.removeValue(forKey: server)
    }
}
