import Foundation

enum BootstrapLaunch {
    static let duration = RegistrationTunnelRoute.duration
    // Same public overlay nodes as Android.
    static let cellHosts = ["87.58.213.193", "78.17.74.27"]
    static let paymentHosts = cellHosts + ["89.37.192.241", PublicApiFailover.hiveIP]
    static let paymentDNS = ["77.88.8.8", "77.88.8.1"]

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

    static func configuration(hash: String, fingerprint: String, password: String, cell: Int,
                              payment: Bool = false, registrationRouting: Bool = false) -> TunnelConfig? {
        let hosts = payment ? paymentHosts : cellHosts
        guard !password.isEmpty, let hash = callHash(hash), hosts.indices.contains(cell) else { return nil }
        return TunnelConfig(deviceId: "boot:\(fingerprint)", serverIP: hosts[cell], serverPort: 56000,
                            password: password, hashes: [hash], workers: 3, address: "",
                            dns: payment ? paymentDNS : (registrationRouting ? RegistrationTunnelRoute.internetDNS : []), mtu: 1200,
                            excludeCIDRs: [], bootstrapDuration: payment ? 300 : duration,
                            paymentRouting: payment ? true : nil, registrationRouting: registrationRouting ? true : nil)
    }
}
