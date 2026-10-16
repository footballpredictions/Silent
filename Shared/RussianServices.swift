import Foundation

struct RussianRoutingPolicy: Codable {
    var schema_version: Int
    var revision: String
    var direct_domains: [String]
    var vpn_domains: [String]
    var enabled: Bool? = nil

    var valid: Bool {
        guard schema_version == 1, revision.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { return false }
        return [direct_domains, vpn_domains].allSatisfy { domains in
            domains.count <= 2000 && domains.allSatisfy { domain in
                !domain.isEmpty && domain.utf8.count <= 253 && domain.split(separator: ".", omittingEmptySubsequences: false).allSatisfy {
                    $0.range(of: "^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", options: .regularExpression) != nil
                }
            }
        }
    }
}

enum RussianServices {
    static var enabled: Bool {
        get { UserDefaults.standard.bool(forKey: "ru_direct") }
        set { UserDefaults.standard.set(newValue, forKey: "ru_direct") }
    }
    private static var cacheURL: URL? { AppIdentity.groupURL?.appendingPathComponent("russian-policy.json") }
    static func policy(enabled: Bool) -> RussianRoutingPolicy? {
        let urls = [cacheURL, Bundle.main.url(forResource: "russian-services-policy", withExtension: "json")].compactMap { $0 }
        for url in urls {
            if let data = try? Data(contentsOf: url), data.count <= 262144,
               var value = try? JSONDecoder().decode(RussianRoutingPolicy.self, from: data), value.valid {
                value.enabled = enabled
                return value
            }
        }
        return nil
    }
    static func refresh() async -> RussianRoutingPolicy? {
        let bases = ["https://89-125-188-100.nip.io", "http://87.58.213.193:9100", "http://78.17.74.27:9100", "http://192.177.26.38:9100", "http://89.37.192.241:9100"]
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 2.5
        configuration.timeoutIntervalForResource = 3
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        for base in bases {
            if Task.isCancelled { return nil }
            do {
                let (data, response) = try await session.data(from: URL(string: base + "/api/vpn/routing-policy")!)
                guard (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 262144 else { continue }
                var value = try JSONDecoder().decode(RussianRoutingPolicy.self, from: data)
                guard value.valid else { continue }
                value.enabled = true
                if let url = cacheURL { try data.write(to: url, options: .atomic) }
                return value
            } catch { /* Keep the last validated policy when offline. */ }
        }
        return nil
    }
}
