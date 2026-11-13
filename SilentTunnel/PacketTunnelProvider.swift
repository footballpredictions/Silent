import Darwin
import Foundation
import NetworkExtension

@_cdecl("silent_relay_event")
func silent_relay_event(_ message: UnsafePointer<CChar>?, _ level: Int32) {
    guard let message else { return }
    autoreleasepool {
        let severity: VPNLogLevel = level == 2 ? .error : (level == 1 ? .success : .info)
        VPNLog.write(String(cString: message), level: severity, source: "WDTT")
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
    private var handshakeCheck: Task<Void, Never>?
    private var bootstrapExpiry: Task<Void, Never>?

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        TunnelBridge.setProvider(self)
        guard var config = loadConfig() else {
            let text = "Не удалось прочитать настройки VPN"
            writeError(text)
            completionHandler(tunnelError(text))
            return
        }
        VPNLog.write(config.bootstrapDuration == nil ? "Запуск основного VPN" : "Запуск временного VPN")
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
        VPNLog.write("Сервер выдал конфигурацию WireGuard", level: .success)
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
                        self?.startPolicyRefresh()
                        self?.scheduleBootstrapExpiry(config.bootstrapDuration)
                        completionHandler(nil)
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

    private func scheduleBootstrapExpiry(_ duration: Int?) {
        bootstrapExpiry?.cancel()
        guard let duration, (1...120).contains(duration) else { return }
        bootstrapExpiry = Task { [weak self] in
            do { try await Task.sleep(nanoseconds: UInt64(duration) * 1_000_000_000) }
            catch { return }
            guard let self, !Task.isCancelled else { return }
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
        handshakeCheck?.cancel()
        handshakeCheck = nil
        bootstrapExpiry?.cancel()
        bootstrapExpiry = nil
        policyRefresh?.cancel()
        policyRefresh = nil
        activeConfig = nil
        TunnelBridge.setProvider(nil)
        wdtt_stop()
        completionHandler()
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

    private func loadConfig() -> TunnelConfig? {
        AppIdentity.readTunnelConfig()
    }

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
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

    private func applyRussianPolicy(_ policy: RussianRoutingPolicy?) -> Bool {
        guard policy == nil || policy?.valid == true else { return false }
        let json: String
        if let policy, let data = try? JSONEncoder().encode(policy), let text = String(data: data, encoding: .utf8) { json = text }
        else { json = "{\"enabled\":false}" }
        return json.withCString { wdtt_set_russian_policy($0) == 0 }
    }

    private func startPolicyRefresh() {
        policyRefresh?.cancel()
        guard activeConfig?.russian?.enabled == true else { return }
        policyRefresh = Task { [weak self] in
            while !Task.isCancelled {
                if let policy = await RussianServices.refresh(), !Task.isCancelled,
                   let self, self.reading, self.activeConfig?.russian?.enabled == true,
                   policy.revision != self.activeConfig?.russian?.revision, self.applyRussianPolicy(policy) {
                    self.activeConfig?.russian = policy
                }
                do { try await Task.sleep(nanoseconds: 300_000_000_000) } catch { return }
            }
        }
    }

    private func makeSettings(_ config: TunnelConfig) -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: config.serverIP)
        let parsed = parseAddress(config.address)
        let ipv4 = NEIPv4Settings(addresses: [parsed.ip], subnetMasks: [parsed.mask])
        if config.bootstrapDuration != nil {
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
