// Run by scripts/build-libwdtt.sh before the native VPN build.
import Foundation

@main
struct SessionsApiPolicyTest {
    @MainActor
    static func main() async throws {
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
        let incompleteList = ServerCatalog.displayList([
            VpnServer(key: "server5", title: "Сервер 5"),
            VpnServer(key: " SERVER2 ", title: "Резервный"),
            VpnServer(key: "server4", title: "Сервер 4"),
            VpnServer(key: "server6", title: "Сервер 6")
        ])
        precondition(ServerCatalog.displayList([]).map(\.key) == ["server1", "server2", "server3", "server4", "server5"])
        precondition(incompleteList.map(\.key) == ["server1", "server2", "server3", "server4", "server5", "server6"])
        precondition(incompleteList[1].title == "Резервный" && incompleteList[3].title == "Сервер 4 для ИИ")
        let hash = "Example_VK-hash-123456789"
        precondition(BootstrapLaunch.callHash("https://vk.ru/call/join/\(hash)?from=invite") == hash)
        precondition(BootstrapLaunch.callHash("https://vk.ru.example/call/join/\(hash)") == nil)
        precondition(BootstrapLaunch.callHash("https://vk.ru/call/join/\(hash)/extra") == nil)
        let local = BootstrapLaunch.configuration(hash: hash, fingerprint: "test-device", password: "test-transport", cell: 0)
        let retry = BootstrapLaunch.configuration(hash: hash, fingerprint: "test-device", password: "test-transport", cell: 1)
        precondition(local?.deviceId == "boot:test-device" && local?.hashes == [hash])
        precondition(local?.bootstrapDuration == 120 && local?.address == "" && local?.serverPort == 56000)
        precondition(local?.serverIP != retry?.serverIP && retry != nil)
        precondition(BootstrapLaunch.configuration(hash: hash, fingerprint: "test-device", password: "", cell: 0) == nil)
        let payment = BootstrapLaunch.configuration(hash: hash, fingerprint: "test-device", password: "test-transport", cell: 1, payment: true)
        precondition(payment?.paymentRouting == true && payment?.bootstrapDuration == 300 && local?.paymentRouting == nil)
        var attempts: [Int] = []
        var stops = 0
        let picked = try await PaymentRoute.choose([1, 2, 3], start: { attempts.append($0) }, probe: {
            attempts.last == 2
        }, stop: { stops += 1; return true })
        precondition(picked == 1 && attempts == [1, 2] && stops == 1)
        precondition(PaymentRoute.isCheckoutURL(URL(string: "https://yoomoney.ru/quickpay/confirm.xml")!))
        precondition(!PaymentRoute.isCheckoutURL(URL(string: "https://yoomoney.ru.example/quickpay/confirm.xml")!))
        let config = VpnConfig(device_id: "device", wg_private_key: "test-private-key", wg_address: "10.66.66.2/32",
                               wg_dns: "1.1.1.1", server_ip: "192.0.2.1", server_port: 56000, server_public_key: "",
                               wdtt_password: "test-transport", vk_hashes: [hash], stream_count: 3, wg_mtu: 1200, selected_server: "server2")
        var cache = ServerConfigCache(account: "account", fingerprint: "fp")
        let now = Date()
        cache.save(config, for: "server1", now: now)
        precondition(cache.config(server: "server1", account: "account", fingerprint: "fp", now: now) == nil)
        cache.save(config, for: "server2", now: now)
        precondition(cache.config(server: "server2", account: "account", fingerprint: "fp", now: now)?.wg_private_key == "")
        precondition(cache.config(server: "server2", account: "other", fingerprint: "fp", now: now) == nil)
        precondition(cache.config(server: "server2", account: "account", fingerprint: "fp", now: now.addingTimeInterval(901)) == nil)
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
