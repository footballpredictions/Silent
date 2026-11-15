// Run by scripts/build-libwdtt.sh before the native VPN build.
import Foundation

@main
struct SessionsApiPolicyTest {
    @MainActor
    static func main() async throws {
        precondition(!VPNSceneOwnership.wasDiscarded("original", openSessions: ["original"]))
        precondition(!VPNSceneOwnership.wasDiscarded("original", openSessions: ["original", "other-window"]))
        precondition(VPNSceneOwnership.wasDiscarded("original", openSessions: ["new-launch"]))
        let active = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps, tunnelActive: true)
        precondition(active.first == "http://10.66.66.1:8000", "Whitelist sessions must reach the API through VPN first")
        precondition(active.count == Set(active).count)
        let offline = PublicApiFailover.bases(preferred: PublicApiFailover.hiveHttps)
        precondition(!offline.contains(PublicApiFailover.tunnelAPI), "VPN-off requests must not wait for a missing tunnel")
        precondition(Array(offline.prefix(2)) == PublicApiFailover.paymentPublicBases)
        precondition(!offline.contains("https://\(PublicApiFailover.hiveIP)"), "Raw IP only serves /api/health")
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
        let profileFixture = Data("""
        {"id":"account","email":"test@example.invalid","display_id":"1",
         "subscription":{"is_active":false,"days_left":0},
         "current_device_id":"this-phone",
         "devices":[{"id":"other-phone","device_name":"iOS","device_type":"ios","is_connected":true},
                    {"id":"this-phone","device_name":"Мой телефон","device_type":"ios","is_connected":false}]}
        """.utf8)
        let profile = try JSONDecoder().decode(UserProfile.self, from: profileFixture)
        precondition(profile.current_device_id == "this-phone" && profile.devices[1].is_connected == false)
        precondition(profile.devices[0].platformLabel == "iOS" && profile.devices[0].customLabel == nil)
        precondition(profile.devices[1].customLabel == "Мой телефон")
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
        precondition(PaymentExitSwitch.Request(host: BootstrapLaunch.paymentHosts[1]).valid)
        precondition(!PaymentExitSwitch.Request(host: "192.0.2.99").valid)
        let badExit = Data("{\"command\":\"other-command\",\"host\":\"78.17.74.27\"}".utf8)
        let decodedBadExit = try JSONDecoder().decode(PaymentExitSwitch.Request.self, from: badExit)
        precondition(!decodedBadExit.valid)
        precondition(payment?.dns == ["77.88.8.8", "77.88.8.1"], "Payment DNS should match Android")
        precondition(PaymentConnectivity.accepts(Data("HTTP/1.1 200 OK\r\n".utf8)))
        precondition(PaymentConnectivity.accepts(Data("HTTP/1.1 302 Found\r\n".utf8)))
        precondition(!PaymentConnectivity.accepts(Data("HTTP/1.1 403 Forbidden\r\n".utf8)))
        precondition(!PaymentConnectivity.accepts(Data("invalid response".utf8)))
        let probeStarted = Date()
        let available = await PaymentConnectivity.anyReachable(["stalled-tls", "working-address"]) { address in
            if address == "working-address" { return true }
            try? await Task.sleep(nanoseconds: 10_000_000_000)
            return false
        }
        precondition(available && Date().timeIntervalSince(probeStarted) < 2,
                     "One stalled TLS address must not hide another working YooMoney address")
        let unavailable = await PaymentConnectivity.anyReachable(["bad-a", "bad-b"]) { _ in false }
        precondition(!unavailable)
        let reservation = PaymentRouteReservation(account: "account", plan: "monthly", connection: "live-exit",
                                                   expires: Date().addingTimeInterval(60), value: "prepared-api")
        precondition(reservation.reuse(account: "account", plan: "monthly", connection: "live-exit") == "prepared-api")
        precondition(reservation.reuse(account: "other", plan: "monthly", connection: "live-exit") == nil)
        precondition(reservation.reuse(account: "account", plan: "annual", connection: "live-exit") == nil)
        precondition(reservation.reuse(account: "account", plan: "monthly", connection: nil) == nil)
        precondition(reservation.reuse(account: "account", plan: "monthly", connection: "new-exit") == nil)
        precondition(reservation.reuse(account: "account", plan: "monthly", connection: "live-exit",
                                       now: Date().addingTimeInterval(61)) == nil)
        var readinessChecks = 0
        let routeReady = try await PaymentRoute.waitUntilReady(attempts: 3, delayNanoseconds: 0) {
            readinessChecks += 1
            return readinessChecks == 2
        }
        precondition(routeReady && readinessChecks == 2, "Do not tear down a tunnel before app routes become ready")
        readinessChecks = 0
        let neverReady = try await PaymentRoute.waitUntilReady(attempts: 3, delayNanoseconds: 0) {
            readinessChecks += 1
            return false
        }
        precondition(!neverReady && readinessChecks == 3, "Readiness retries must remain bounded")
        do {
            _ = try await PaymentRoute.waitUntilReady(attempts: 3, delayNanoseconds: 0) { throw CancellationError() }
            preconditionFailure("Readiness ignored cancellation")
        } catch is CancellationError {}
        guard let mail = BootstrapLaunch.configuration(hash: hash, fingerprint: "test-device", password: "test-transport",
                                                       cell: 0, registrationRouting: true) else {
            preconditionFailure("Email confirmation needs a temporary Internet route")
        }
        precondition(mail.bootstrapRoutesInternet && mail.bootstrapDuration == BootstrapLaunch.duration)
        precondition(mail.dns == ["1.1.1.1", "9.9.9.9"] && mail.paymentRouting == nil)
        precondition(local?.bootstrapRoutesInternet == false && retry?.bootstrapRoutesInternet == false &&
                     payment?.bootstrapRoutesInternet == true)
        let restoredMail = try JSONDecoder().decode(TunnelConfig.self, from: JSONEncoder().encode(mail))
        precondition(restoredMail.bootstrapRoutesInternet && restoredMail.paymentRouting == nil)
        if let local {
            var running = local
            running.address = "10.66.66.8/32"
            guard let promoted = RegistrationTunnelRoute.enable(on: running) else {
                preconditionFailure("The login tunnel should be able to add a route for Mail")
            }
            precondition(promoted.registrationRouting == true && promoted.bootstrapRoutesInternet)
            precondition(promoted.address == running.address && promoted.deviceId == running.deviceId)
            precondition(promoted.serverIP == running.serverIP && promoted.serverPort == running.serverPort)
            precondition(promoted.workers == running.workers && promoted.hashes == running.hashes)
            precondition(promoted.password == running.password && promoted.mtu == running.mtu)
            precondition(promoted.dns == mail.dns && promoted.bootstrapDuration == mail.bootstrapDuration)
            running.bootstrapDuration = nil
            precondition(RegistrationTunnelRoute.enable(on: running) == nil)
        } else {
            preconditionFailure("Expected the login VPN configuration")
        }
        if let payment { precondition(RegistrationTunnelRoute.enable(on: payment) == nil) }
        var attempts: [Int] = []
        var stops = 0
        let picked = try await PaymentRoute.choose([1, 2, 3], start: { attempts.append($0) }, probe: {
            attempts.last == 2
        }, stop: { stops += 1; return true })
        precondition(picked == 1 && attempts == [1, 2] && stops == 1)
        attempts = []
        do {
            _ = try await PaymentRoute.choose([1, 2], start: { attempts.append($0) }, probe: {
                throw URLError(.userAuthenticationRequired)
            }, stop: { preconditionFailure("A definitive API rejection must reach the payment caller") })
            preconditionFailure("A definitive API rejection must propagate")
        } catch let error as URLError {
            precondition(error.code == .userAuthenticationRequired && attempts == [1])
        }
        precondition(PaymentRoute.isCheckoutURL(URL(string: "https://yoomoney.ru/quickpay/confirm.xml")!))
        precondition(!PaymentRoute.isCheckoutURL(URL(string: "https://yoomoney.ru.example/quickpay/confirm.xml")!))
        let config = VpnConfig(device_id: "device", wg_private_key: "test-private-key", wg_address: "10.66.66.2/32",
                               wg_dns: "1.1.1.1", server_ip: "192.0.2.1", server_port: 56000, server_public_key: "",
                               wdtt_password: "test-transport", vk_hashes: [hash], stream_count: 3, wg_mtu: 1200, selected_server: "server2")
        var cache = ServerConfigCache(account: "account", fingerprint: "fp")
        let now = Date()
        cache.save(config, for: "server1", now: now)
        precondition(cache.config(server: "server1", account: "account", fingerprint: "fp", deviceId: "device", now: now) == nil)
        cache.save(config, for: "server2", now: now)
        let persisted = try JSONDecoder().decode(ServerConfigCache.self, from: JSONEncoder().encode(cache))
        precondition(persisted.config(server: "server2", account: "account", fingerprint: "fp", deviceId: "device", now: now)?.wg_private_key == "")
        precondition(persisted.config(server: "server2", account: "other", fingerprint: "fp", deviceId: "device", now: now) == nil)
        precondition(persisted.config(server: "server2", account: "account", fingerprint: "fp", deviceId: "replacement", now: now) == nil)
        let later = now.addingTimeInterval(901)
        precondition(persisted.config(server: "server2", account: "account", fingerprint: "fp", deviceId: "device", now: later) != nil)
        precondition(persisted.config(server: "server2", account: "account", fingerprint: "fp", deviceId: "device",
                                      maxAge: ServerConfigCache.refreshInterval, now: later) == nil)
        precondition(persisted.config(server: "server2", account: "account", fingerprint: "fp", deviceId: "device",
                                      now: now.addingTimeInterval(ServerConfigCache.lifetime)) == nil)
        let partial = Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{".utf8)
        let incomplete = try BootstrapHTTPResponse.parse(partial, complete: false)
        precondition(incomplete == nil)
        let response = try BootstrapHTTPResponse.parse(partial + Data("}".utf8), complete: false)
        precondition(response?.0 == 200 && response?.1 == Data("{}".utf8))
        do {
            _ = try BootstrapHTTPResponse.parse(partial, complete: true)
            preconditionFailure("Truncated response was accepted")
        } catch let error as URLError { precondition(error.code == .badServerResponse) }
        func relay(_ offset: Double, _ message: String, level: VPNLogLevel = .info,
                   source: String = "WDTT", key: String? = nil) -> VPNLogEntry {
            VPNLogEntry(date: now.addingTimeInterval(offset), level: level, source: source, message: message, key: key)
        }
        let log = VPNLogRow.grouped([
            relay(0, "Воркер №1 · DTLS установлен"),
            relay(1, "Воркер №2 активен · активных каналов: 2"),
            relay(2, "Воркер №2 · DTLS установлен"),
            relay(3, "Воркер №3 активен · активных каналов: 3"),
            relay(4, "Воркер №1 отключён · активных каналов: 2"),
            relay(5, "Воркер №4 · DTLS установлен", level: .error),
            relay(6, "DTLS установлен", source: "Приложение"),
            relay(0.5, "[СТАТИСТИКА] Активных: 1 | Трафик: 0.00 МБ", key: "stats"),
            relay(7, "[СТАТИСТИКА] Активных: 3 | Трафик: 0.04 МБ", key: "stats"),
        ])
        precondition(log.map(\.count) == [2, 2, 1, 1, 1, 2])
        precondition(log[0].entry.message == "DTLS установлен" && log[0].line.hasSuffix("(×2)"))
        precondition(log[1].entry.message == "Воркер активен · активных каналов: 3")
        precondition(log.last?.line.contains("[СТАТИСТИКА] Активных: 3 | Трафик: 0.04 МБ (×2)") == true)
        precondition(log.last?.line.contains("[WDTT] [СТАТИСТИКА]") == false)
        let changingMetrics = VPNLogRow.grouped([
            relay(0, "[РЕСУРСЫ] Go heap: 9.0 МБ · GC CPU: 0.1% · задач: 854"),
            relay(1, "[СТАТИСТИКА] Активных: 29/63 | Трафик: 0.13 МБ"),
            relay(2, "Получение конфигурации · 10%", source: "Приложение"),
            relay(3, "[РЕСУРСЫ] Go heap: 23.8 МБ · GC CPU: 5.7% · задач: 931"),
            relay(4, "Получение конфигурации · 95%", source: "Приложение"),
            relay(5, "[СТАТИСТИКА] Активных: 63/63 | Трафик: 202.91 МБ"),
        ])
        precondition(changingMetrics.count == 3 && changingMetrics.allSatisfy { $0.count == 2 })
        precondition(changingMetrics[0].entry.message.contains("5.7%") && changingMetrics[0].entry.message.contains("931"))
        precondition(changingMetrics[1].entry.message.contains("95%"))
        precondition(changingMetrics[2].entry.message.contains("202.91"))
        let distinctErrors = VPNLogRow.grouped([
            relay(0, "TURN: ошибка продления канала · код 437", level: .error),
            relay(1, "TURN: ошибка продления канала · код 403", level: .error),
            relay(2, "Сетевой модуль вернул ошибку 6", level: .error, source: "Туннель"),
            relay(3, "Сетевой модуль вернул ошибку 12", level: .error, source: "Туннель"),
        ])
        precondition(distinctErrors.count == 4, "Distinct failure codes must not disappear in metric grouping")
        print("Sessions API policy and VPN journal: PASS")
    }
}
