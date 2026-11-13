// Run by scripts/build-libwdtt.sh before the native VPN build.
import Foundation

@main
struct SessionsApiPolicyTest {
    static func main() throws {
        let active = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps, tunnelActive: true)
        precondition(active.first == "http://10.66.66.1:8000", "Whitelist sessions must reach the API through VPN first")
        precondition(active.count == Set(active).count)
        let offline = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps)
        precondition(!offline.contains(PublicApiFailover.tunnelAPI), "VPN-off requests must not wait for a missing tunnel")
        precondition(PublicApiFailover.bootstrapPorts == [443, 2083])
        precondition(URL(string: PublicApiFailover.hiveAlternateHTTPS)?.host == PublicApiFailover.hiveHost)
        let url = PublicApiFailover.serverQuery("api/vpn/servers", fingerprint: "device&123")
        let query = URLComponents(string: url)?.queryItems
        precondition(query == [URLQueryItem(name: "fingerprint", value: "device&123")])
        precondition(offline.contains(PublicApiFailover.hiveAlternateHTTPS))
        for code in [401, 402, 403, 404] {
            precondition(!PublicApiFailover.shouldTryNextBase(httpCode: code))
        }
        precondition(PublicApiFailover.shouldTryNextBase(httpCode: 503))
        let partial = Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{".utf8)
        let incomplete = try BootstrapHTTPResponse.parse(partial, complete: false)
        precondition(incomplete == nil)
        let response = try BootstrapHTTPResponse.parse(partial + Data("}".utf8), complete: false)
        precondition(response?.0 == 200 && response?.1 == Data("{}".utf8))
        do {
            _ = try BootstrapHTTPResponse.parse(partial, complete: true)
            preconditionFailure("Truncated response was accepted")
        } catch let error as URLError { precondition(error.code == .badServerResponse) }
        print("Sessions API policy: PASS")
    }
}
