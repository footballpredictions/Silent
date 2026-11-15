import Darwin
import Foundation
import Network
import NetworkExtension

@_cdecl("silent_relay_event")
func silent_relay_event(_ message: UnsafePointer<CChar>?, _ level: Int32) {
    guard let message else { return }
    autoreleasepool {
        let severity: VPNLogLevel = level == 2 ? .error : (level == 1 ? .success : .info)
        let text = String(cString: message)
        VPNLog.write(text, level: severity, source: "WDTT", key: text.hasPrefix("[СТАТИСТИКА]") ? "stats" : nil)
    }
}

enum TunnelBridge {
    private static let lock = NSLock()
    private static weak var provider: PacketTunnelProvider?

    static func setProvider(_ value: PacketTunnelProvider?) {
        lock.lock()
        defer { lock.unlock() }
        provider = value
    }

    static func currentProvider() -> PacketTunnelProvider? {
        lock.lock()
        defer { lock.unlock() }
        return provider
    }
}

@_cdecl("silent_packet_out")
func silent_packet_out(_ data: UnsafePointer<UInt8>?, _ len: Int32) {
    guard let data, len > 0 else { return }
    autoreleasepool {
        guard let provider = TunnelBridge.currentProvider() else { return }
        let buf = Data(bytes: data, count: Int(len))
        switch data.pointee >> 4 {
        case 4: _ = provider.packetFlow.writePackets([buf], withProtocols: [NSNumber(value: AF_INET)])
        case 6: _ = provider.packetFlow.writePackets([buf], withProtocols: [NSNumber(value: AF_INET6)])
        default: break
        }
    }
}

class PacketTunnelProvider: NEPacketTunnelProvider {
    private var reading = false
    private var activeConfig: TunnelConfig?
    private var policyRefresh: Task<Void, Never>?
    private var receivedPolicy: String?
    private var handshakeCheck: Task<Void, Never>?
    private var bootstrapExpiry: Task<Void, Never>?
    private var bootstrapDeadline: Date?
    private let engineQueue = DispatchQueue(label: "silent.tunnel.engine", qos: .userInitiated)
    private var paymentSwitch: Task<Void, Never>?
    private var paymentSwitchID: UUID?
    private var pathMonitor: NWPathMonitor?
    private let pathQueue = DispatchQueue(label: "silent.tunnel.path")

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        let engineRevision: String
        if let revision = wdtt_engine_revision() { engineRevision = String(cString: revision); free(revision) }
        else { engineRevision = "unknown" }
        VPNLog.write(AppIdentity.buildDescription + " · движок " + String(engineRevision.prefix(12)), source: "Версия VPN", key: "tunnel-build")
        reasserting = false
        TunnelBridge.setProvider(self)
        guard var config = loadConfig() else {
            let text = "Не удалось прочитать настройки VPN"
            writeError(text)
            completionHandler(tunnelError(text))
            return
        }
        if config.registrationRouting == true {
            VPNLog.write("Запуск временного VPN для почты")
        } else {
            VPNLog.write(config.bootstrapDuration == nil ? "Запуск основного VPN" : "Запуск временного VPN")
        }
        let os = ProcessInfo.processInfo.operatingSystemVersion
        var hardware = utsname()
        let model = uname(&hardware) == 0
            ? withUnsafeBytes(of: hardware.machine) { String(decoding: $0.prefix(while: { $0 != 0 }), as: UTF8.self) }
            : "iPhone"
        VPNLog.write("\(model) · iOS \(os.majorVersion).\(os.minorVersion).\(os.patchVersion) · ABI=arm64", source: "Устройство")
        if config.bootstrapDuration == nil, UUID(uuidString: config.deviceId) != nil {
            VPNLog.write("libclient device-id: \(config.deviceId.prefix(4))… (\(config.deviceId.count) симв.)", source: "WDTT")
        }
        if wdtt_engine_linked() == 0 {
            let text = "Туннель не собран. На Mac запустите scripts/build-libwdtt.sh и заново сделайте Archive."
            writeError(text)
            completionHandler(tunnelError(text))
            return
        }

        let work = AppIdentity.workURL?.path ?? NSTemporaryDirectory()
        try? FileManager.default.createDirectory(atPath: work, withIntermediateDirectories: true)
        wdtt_set_output(silent_packet_out)
        wdtt_set_journal(silent_relay_event)
        wdtt_set_start_timeout(config.paymentRouting == true ? 12 : 0)
        let code = config.hashes.joined(separator: ",").withCString { hashes in
            config.password.withCString { password in
                config.deviceId.withCString { deviceId in
                    config.serverIP.withCString { ip in
                        work.withCString { dir in
                            wdtt_start(ip, Int32(config.serverPort), hashes, password, deviceId, Int32(config.workers), Int32(config.mtu), dir)
                        }
                    }
                }
            }
        }
        if code != 0 {
            let raw: String
            if let error = wdtt_last_error() {
                raw = String(cString: error)
                free(error)
            } else {
                raw = "Не удалось запустить сетевой модуль"
            }
            let reason = code == 6 ? ": \(raw)" : ""
            VPNLog.write("Сетевой модуль вернул ошибку \(code)\(reason)", level: .error)
            wdtt_stop()
            writeError(raw)
            completionHandler(tunnelError(raw))
            return
        }

        guard let address = wdtt_assigned_address() else {
            wdtt_stop()
            let text = "Сервер не выдал адрес VPN"
            writeError(text)
            completionHandler(tunnelError(text))
            return
        }
        config.address = String(cString: address)
        free(address)
        guard applyRussianPolicy(config.russian) else {
            wdtt_stop()
            let text = "Не удалось применить правила российских сервисов"
            writeError(text)
            completionHandler(tunnelError(text))
            return
        }
        activeConfig = config
        let settings = makeSettings(config)
        setTunnelNetworkSettings(settings) { [weak self] error in
            if let error {
                wdtt_stop()
                self?.writeError(error.localizedDescription)
                completionHandler(error)
                return
            }
            self?.reading = true
            self?.readLoop()
            VPNLog.write("Настройки маршрутизации применены. Ожидание WireGuard")
            guard let self else { completionHandler(CancellationError()); return }
            self.handshakeCheck = Task { [weak self] in
                for _ in 0..<60 {
                    guard !Task.isCancelled else { completionHandler(CancellationError()); return }
                    if wdtt_has_handshake() != 0 {
                        VPNLog.write("Рукопожатие WireGuard подтверждено", level: .success)
                        self?.startPathMonitor()
                        self?.startPolicyRefresh()
                        self?.scheduleBootstrapExpiry(config.bootstrapDuration, payment: config.paymentRouting == true)
                        completionHandler(nil)
                        if config.bootstrapDuration == nil { wdtt_expand_workers() }
                        return
                    }
                    do { try await Task.sleep(nanoseconds: 250_000_000) }
                    catch { completionHandler(error); return }
                }
                guard !Task.isCancelled, let self else { completionHandler(CancellationError()); return }
                self.reading = false
                self.activeConfig = nil
                wdtt_stop()
                let text = "Сервер не ответил на рукопожатие VPN. Попробуйте другой сервер."
                self.writeError(text)
                completionHandler(self.tunnelError(text))
            }
        }
    }

    private func scheduleBootstrapExpiry(_ duration: Int?, payment: Bool) {
        bootstrapExpiry?.cancel()
        bootstrapDeadline = nil
        guard let duration, (1...(payment ? 300 : RegistrationTunnelRoute.duration)).contains(duration) else { return }
        let deadline = Date().addingTimeInterval(TimeInterval(duration))
        bootstrapDeadline = deadline
        bootstrapExpiry = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(duration) * 1_000_000_000) }
            catch { return }
            guard let self, !Task.isCancelled, self.bootstrapDeadline == deadline else { return }
            let text = "Время временного VPN истекло"
            self.writeError(text)
            self.cancelTunnelWithError(self.tunnelError(text))
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        VPNLog.write("Остановка расширения iOS: \(reason.rawValue)", level: reason == .userInitiated ? .info : .error)
        if reason != .userInitiated, reason != .none,
           AppIdentity.errorURL.map({ !FileManager.default.fileExists(atPath: $0.path) }) == true {
            writeError("iOS завершила VPN (код остановки \(reason.rawValue))")
        }
        reading = false
        pathMonitor?.cancel()
        pathMonitor = nil
        handshakeCheck?.cancel()
        handshakeCheck = nil
        bootstrapExpiry?.cancel()
        bootstrapExpiry = nil
        bootstrapDeadline = nil
        policyRefresh?.cancel()
        policyRefresh = nil
        receivedPolicy = nil
        paymentSwitch?.cancel()
        paymentSwitch = nil
        paymentSwitchID = nil
        activeConfig = nil
        TunnelBridge.setProvider(nil)
        wdtt_cancel_start()
        engineQueue.async { wdtt_stop(); completionHandler() }
    }

    private func readLoop() {
        guard reading else { return }
        packetFlow.readPackets { [weak self] packets, _ in
            guard let self, self.reading else { return }
            for packet in packets {
                packet.withUnsafeBytes { raw in
                    guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return }
                    wdtt_input(base, Int32(packet.count))
                }
            }
            self.readLoop()
        }
    }

    override func sleep(completionHandler: @escaping () -> Void) {
        VPNLog.write("Устройство переходит в сон", source: "Сеть")
        completionHandler()
    }

    override func wake() {
        guard reading else { return }
        VPNLog.write("Устройство проснулось · проверяем привязку каналов к сети", source: "Сеть")
        wdtt_network_event(0)
    }

    private func startPathMonitor() {
        pathMonitor?.cancel()
        let monitor = NWPathMonitor()
        var previous: String?
        var wasUnavailable = false
        monitor.pathUpdateHandler = { [weak self, weak monitor] path in
            guard let self, let monitor, self.pathMonitor === monitor, self.reading else { return }
            guard path.status == .satisfied else { wasUnavailable = true; return }
            guard let identity = self.physicalPathIdentity(path) else { return }
            if let previous, previous != identity {
                VPNLog.write("Физическая сеть изменилась · обновляем привязанные к ней UDP-сокеты", source: "Сеть")
                wdtt_network_event(1)
            } else if wasUnavailable {
                VPNLog.write("Сеть вернулась · проверяем прежние каналы", source: "Сеть")
                wdtt_network_event(0)
            }
            previous = identity
            wasUnavailable = false
        }
        pathMonitor = monitor
        monitor.start(queue: pathQueue)
    }

    private func physicalPathIdentity(_ path: Network.NWPath) -> String? {
        let names = Set(path.availableInterfaces.filter {
            $0.type != .other && $0.type != .loopback && path.usesInterfaceType($0.type)
        }.map(\.name))
        guard !names.isEmpty else { return nil }
        var first: UnsafeMutablePointer<ifaddrs>?
        var values: [String] = []
        if getifaddrs(&first) == 0 {
            defer { if let first { freeifaddrs(first) } }
            var current = first
            while let entry = current {
                defer { current = entry.pointee.ifa_next }
                let name = String(cString: entry.pointee.ifa_name)
                guard names.contains(name), let address = entry.pointee.ifa_addr,
                      [AF_INET, AF_INET6].contains(Int32(address.pointee.sa_family)) else { continue }
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                if getnameinfo(address, socklen_t(address.pointee.sa_len), &host, socklen_t(host.count),
                               nil, 0, NI_NUMERICHOST) == 0 {
                    values.append(name + ":" + String(cString: host))
                }
            }
        }
        // Addresses are compared only in memory, never written to the journal.
        return names.sorted().joined(separator: ",") + "|" + values.sorted().joined(separator: ",")
    }

    private func loadConfig() -> TunnelConfig? {
        AppIdentity.readTunnelConfig()
    }

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        if let request = try? JSONDecoder().decode(PaymentExitSwitch.Request.self, from: messageData), request.valid {
            switchPaymentExit(request.host, completionHandler: completionHandler)
            return
        }
        if messageData == RegistrationTunnelRoute.request {
            enableRegistrationInternet(completionHandler)
            return
        }
        if messageData == Data("policy-received".utf8) {
            completionHandler?(receivedPolicy.map { Data($0.utf8) })
            return
        }
        guard messageData == Data("site-routing".utf8), var config = loadConfig() else {
            completionHandler?(nil)
            return
        }
        let previous = activeConfig
        guard let address = previous?.address else { completionHandler?(nil); return }
        config.address = address
        guard applyRussianPolicy(config.russian) else { completionHandler?(nil); return }
        setTunnelNetworkSettings(makeSettings(config)) { [weak self] error in
            if error == nil { self?.activeConfig = config; self?.startPolicyRefresh() }
            else {
                _ = self?.applyRussianPolicy(previous?.russian)
                if let previous, let url = AppIdentity.configURL {
                    try? JSONEncoder().encode(previous).write(to: url, options: .atomic)
                }
            }
            completionHandler?(error == nil ? Data("ok".utf8) : nil)
        }
    }

    private func switchPaymentExit(_ host: String, completionHandler: ((Data?) -> Void)?) {
        guard reading, paymentSwitch == nil, var config = activeConfig, config.paymentRouting == true,
              let deadline = bootstrapDeadline, deadline > Date() else {
            completionHandler?(nil)
            return
        }
        config.serverIP = host
        let target = config
        reasserting = true
        let switchID = UUID()
        paymentSwitchID = switchID
        VPNLog.write("Оплата · меняем выход внутри временного VPN")
        paymentSwitch = Task { [weak self] in
            guard let self else { completionHandler?(nil); return }
            defer {
                if self.paymentSwitchID == switchID { self.paymentSwitch = nil; self.paymentSwitchID = nil }
            }
            do {
                let updated: TunnelConfig = try await withCheckedThrowingContinuation { continuation in
                    self.engineQueue.async {
                        guard self.reading else { continuation.resume(throwing: CancellationError()); return }
                        do { continuation.resume(returning: try self.startPaymentEngine(target)) }
                        catch { continuation.resume(throwing: error) }
                    }
                }
                try Task.checkCancellation()
                guard self.reading, self.bootstrapDeadline == deadline, deadline > Date() else { throw CancellationError() }
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    self.setTunnelNetworkSettings(self.makeSettings(updated)) { error in
                        if let error { continuation.resume(throwing: error) }
                        else { continuation.resume() }
                    }
                }
                for _ in 0..<60 {
                    try Task.checkCancellation()
                    guard self.reading, deadline > Date() else { throw CancellationError() }
                    if wdtt_has_handshake() != 0 {
                        self.activeConfig = updated
                        if let url = AppIdentity.configURL { try JSONEncoder().encode(updated).write(to: url, options: .atomic) }
                        self.reasserting = false
                        VPNLog.write("Оплата · новый выход подтвердил WireGuard", level: .success)
                        completionHandler?(try? JSONEncoder().encode(PaymentExitSwitch.Reply(success: true, error: nil)))
                        return
                    }
                    try await Task.sleep(nanoseconds: 250_000_000)
                }
                throw self.tunnelError("Новый выход не ответил на рукопожатие")
            } catch {
                // Keep the outer iOS tunnel and its original deadline alive so
                // the app can try the next exit without another VPN profile start.
                let message = Task.isCancelled ? "Переключение отменено" : error.localizedDescription
                completionHandler?(try? JSONEncoder().encode(PaymentExitSwitch.Reply(success: false, error: message)))
            }
        }
    }

    private func startPaymentEngine(_ original: TunnelConfig) throws -> TunnelConfig {
        var config = original
        let work = AppIdentity.workURL?.path ?? NSTemporaryDirectory()
        wdtt_set_start_timeout(12)
        let code = config.hashes.joined(separator: ",").withCString { hashes in
            config.password.withCString { password in
                config.deviceId.withCString { deviceId in
                    config.serverIP.withCString { ip in
                        work.withCString { dir in
                            wdtt_start(ip, Int32(config.serverPort), hashes, password, deviceId,
                                       Int32(config.workers), Int32(config.mtu), dir)
                        }
                    }
                }
            }
        }
        guard code == 0 else {
            let message: String
            if let error = wdtt_last_error() { message = String(cString: error); free(error) }
            else { message = "Не удалось подготовить новый выход" }
            throw tunnelError(message)
        }
        guard let address = wdtt_assigned_address() else { throw tunnelError("Выход не выдал адрес VPN") }
        config.address = String(cString: address)
        free(address)
        guard applyRussianPolicy(config.russian) else { throw tunnelError("Не удалось применить маршруты выхода") }
        return config
    }

    private func enableRegistrationInternet(_ completionHandler: ((Data?) -> Void)?) {
        guard reading, let active = activeConfig, let deadline = bootstrapDeadline, deadline > Date(),
              let updated = RegistrationTunnelRoute.enable(on: active) else {
            completionHandler?(nil)
            return
        }
        if active.registrationRouting == true {
            completionHandler?(try? JSONEncoder().encode(deadline))
            return
        }
        setTunnelNetworkSettings(makeSettings(updated)) { [weak self] error in
            guard let self, error == nil, self.reading, self.bootstrapDeadline == deadline else {
                completionHandler?(nil)
                return
            }
            self.activeConfig = updated
            self.scheduleBootstrapExpiry(updated.bootstrapDuration, payment: false)
            VPNLog.write("Маршрут для почты добавлен к временному VPN", level: .success)
            completionHandler?(self.bootstrapDeadline.flatMap { try? JSONEncoder().encode($0) })
        }
    }

    private func applyRussianPolicy(_ policy: RussianRoutingPolicy?) -> Bool {
        guard policy == nil || policy?.valid == true else { return false }
        let json: String
        if let policy, let data = try? JSONEncoder().encode(policy), let text = String(data: data, encoding: .utf8) { json = text }
        else { json = "{\"enabled\":false}" }
        return json.withCString { wdtt_set_russian_policy($0) == 0 }
    }

    private func startPolicyRefresh() {
        policyRefresh?.cancel()
        receivedPolicy = nil
        guard activeConfig?.russian?.enabled == true else { return }
        policyRefresh = Task { [weak self] in
            while !Task.isCancelled {
                if let policy = await RussianServices.refresh(), !Task.isCancelled,
                   let self, self.reading, self.activeConfig?.russian?.enabled == true {
                    if policy.revision == self.activeConfig?.russian?.revision || self.applyRussianPolicy(policy) {
                        self.activeConfig?.russian = policy
                        self.receivedPolicy = policy.revision
                    }
                }
                do { try await Task.sleep(nanoseconds: 300_000_000_000) } catch { return }
            }
        }
    }

    private func makeSettings(_ config: TunnelConfig) -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: config.serverIP)
        let parsed = parseAddress(config.address)
        let ipv4 = NEIPv4Settings(addresses: [parsed.ip], subnetMasks: [parsed.mask])
        if config.bootstrapDuration != nil && !config.bootstrapRoutesInternet {
            ipv4.includedRoutes = [NEIPv4Route(destinationAddress: "10.66.66.1", subnetMask: "255.255.255.255")]
            settings.ipv4Settings = ipv4
            settings.mtu = NSNumber(value: config.mtu)
            return settings
        }
        let russian = config.russian?.enabled == true
        let sites = russian ? [] : excludeRoutes(config.excludeCIDRs)
        if config.sitesWhitelist == true && !russian {
            let serviceRoutes = excludeRoutes(["10.66.66.0/24"] + (config.dns.isEmpty ? ["1.1.1.1"] : config.dns))
            ipv4.includedRoutes = sites + serviceRoutes
            ipv4.excludedRoutes = excludeRoutes([config.serverIP])
        } else {
            ipv4.includedRoutes = [NEIPv4Route.default()]
            if !sites.isEmpty { ipv4.excludedRoutes = sites }
        }
        settings.ipv4Settings = ipv4

        if config.sitesWhitelist != true || russian {
            let ipv6 = NEIPv6Settings(addresses: ["fd7a:115c:a1e0::1"], networkPrefixLengths: [128])
            ipv6.includedRoutes = [NEIPv6Route.default()]
            settings.ipv6Settings = ipv6
        }

        settings.mtu = NSNumber(value: config.mtu)
        let servers = config.dns.filter { !$0.isEmpty }
        let dns = NEDNSSettings(servers: servers.isEmpty ? ["1.1.1.1"] : servers)
        dns.matchDomains = [""]
        settings.dnsSettings = dns
        return settings
    }

    private func parseAddress(_ raw: String) -> (ip: String, mask: String) {
        let parts = raw.split(separator: "/").map(String.init)
        let ip = parts.first?.trimmingCharacters(in: .whitespaces) ?? "10.66.66.2"
        let prefix = Int(parts.count > 1 ? parts[1] : "32") ?? 32
        return (ip, subnetMask(prefix: prefix))
    }

    private func subnetMask(prefix: Int) -> String {
        let p = min(max(prefix, 0), 32)
        let mask: UInt32 = p == 0 ? 0 : ~UInt32(0) << UInt32(32 - p)
        return "\((mask >> 24) & 255).\((mask >> 16) & 255).\((mask >> 8) & 255).\(mask & 255)"
    }

    private func excludeRoutes(_ rules: [String]) -> [NEIPv4Route] {
        var routes: [NEIPv4Route] = []
        for rule in rules.prefix(100) {
            let item = rule.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            if item.isEmpty { continue }
            if item.contains("/"), let route = routeFromCIDR(item) {
                routes.append(route)
                continue
            }
            if isIPv4(item) {
                routes.append(NEIPv4Route(destinationAddress: item, subnetMask: "255.255.255.255"))
                continue
            }
            let host = item.split(separator: "/").first.map(String.init) ?? item
            for ip in resolveIPv4(host) {
                routes.append(NEIPv4Route(destinationAddress: ip, subnetMask: "255.255.255.255"))
            }
        }
        return routes
    }

    private func routeFromCIDR(_ cidr: String) -> NEIPv4Route? {
        let parts = cidr.split(separator: "/").map(String.init)
        guard parts.count == 2, isIPv4(parts[0]), let prefix = Int(parts[1]) else { return nil }
        return NEIPv4Route(destinationAddress: parts[0], subnetMask: subnetMask(prefix: prefix))
    }

    private func isIPv4(_ s: String) -> Bool {
        let bits = s.split(separator: ".")
        guard bits.count == 4 else { return false }
        return bits.allSatisfy { Int($0).map { (0...255).contains($0) } ?? false }
    }

    private func resolveIPv4(_ host: String) -> [String] {
        var hints = addrinfo()
        hints.ai_family = AF_INET
        hints.ai_socktype = SOCK_DGRAM
        var res: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, nil, &hints, &res) == 0, let first = res else { return [] }
        defer { freeaddrinfo(first) }
        var out: [String] = []
        var ptr: UnsafeMutablePointer<addrinfo>? = first
        while let node = ptr {
            if node.pointee.ai_family == AF_INET, let sa = node.pointee.ai_addr {
                var addr = sa.withMemoryRebound(to: sockaddr_in.self, capacity: 1) { $0.pointee.sin_addr }
                var buf = [CChar](repeating: 0, count: Int(INET_ADDRSTRLEN))
                if inet_ntop(AF_INET, &addr, &buf, socklen_t(INET_ADDRSTRLEN)) != nil {
                    out.append(String(cString: buf))
                }
            }
            ptr = node.pointee.ai_next
        }
        return out
    }

    private func writeError(_ text: String) {
        VPNLog.write("Сетевое расширение не завершило текущий этап", level: .error)
        guard let url = AppIdentity.errorURL else { return }
        try? text.write(to: url, atomically: true, encoding: .utf8)
    }

    private func tunnelError(_ text: String) -> NSError {
        NSError(domain: "SilentVPN", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
