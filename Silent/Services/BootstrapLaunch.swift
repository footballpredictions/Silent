import Foundation

enum BootstrapLaunch {
    static let duration = 120
    // Same public overlay nodes as Android. The login route is limited to the API gateway.
    static let cellHosts = ["87.58.213.193", "78.17.74.27"]

    static func callHash(_ input: String) -> String? {
        let raw = input.trimmingCharacters(in: .whitespacesAndNewlines)
        let candidate: String
        if let url = URLComponents(string: raw), url.scheme != nil {
            let host = url.host?.lowercased()
            let parts = url.path.split(separator: "/")
            guard url.scheme?.lowercased() == "https", host == "vk.ru" || host == "vk.com",
                  url.user == nil, url.password == nil, url.port == nil,
                  parts.count == 3, parts[0] == "call", parts[1] == "join" else { return nil }
            candidate = String(parts[2])
        } else {
            candidate = raw
        }
        guard (16...128).contains(candidate.utf8.count), candidate.utf8.allSatisfy({
            (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95
        }) else { return nil }
        return candidate
    }

    static func configuration(hash: String, fingerprint: String, password: String, cell: Int) -> TunnelConfig? {
        guard !password.isEmpty, let hash = callHash(hash), cellHosts.indices.contains(cell) else { return nil }
        return TunnelConfig(deviceId: "boot:\(fingerprint)", serverIP: cellHosts[cell], serverPort: 56000,
                            password: password, hashes: [hash], workers: 3, address: "", dns: [], mtu: 1200,
                            excludeCIDRs: [], bootstrapDuration: duration)
    }
}
