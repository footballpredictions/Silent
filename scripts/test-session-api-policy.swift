// On macOS, from ios/: swiftc -parse-as-library Silent/Services/PublicApiFailover.swift scripts/test-session-api-policy.swift -o /tmp/silent-session-policy && /tmp/silent-session-policy
import Foundation

@main
struct SessionsApiPolicyTest {
    static func main() {
        let active = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps, tunnelActive: true)
        precondition(active.first == "http://10.66.66.1:8000", "Whitelist sessions must reach the API through VPN first")
        precondition(active.count == Set(active).count)
        let offline = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps)
        precondition(!offline.contains(PublicApiFailover.tunnelAPI), "VPN-off requests must not wait for a missing tunnel")
        let bootstrap = PublicApiFailover.bootstrapHTTPS.compactMap(URL.init(string:))
        precondition(bootstrap.count == 2 && bootstrap.allSatisfy { $0.scheme == "https" })
        precondition(bootstrap[0].host == bootstrap[1].host && bootstrap[1].port == 2083,
                     "Bootstrap fallback must preserve certificate hostname and change ports")
        precondition(offline.contains(PublicApiFailover.hiveAlternateHTTPS))
        for code in [401, 402, 403, 404] {
            precondition(!PublicApiFailover.shouldTryNextBase(httpCode: code))
        }
        precondition(PublicApiFailover.shouldTryNextBase(httpCode: 503))
        print("Sessions API policy: PASS")
    }
}
