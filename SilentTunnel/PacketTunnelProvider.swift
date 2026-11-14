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
        VPNLog.write(text, level: severity, source: "WDTT", key: text.hasPrefix("Статистика ·") ? "stats" : nil)
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
    private let stateQueue = DispatchQueue(label: "silent.tunnel.state")
    private let engineQueue = DispatchQueue(label: "silent.tunnel.engine", qos: .userInitiated)
    private var generation = 0
    private var monitor: NWPathMonitor?
    private var timer: DispatchSourceTimer?
    private var path: String?
    private var activeConfig: TunnelConfig?
    private var startup: ((Error?) -> Void)?
    private var handshake: (until: TimeInterval, done: (Bool) -> Void)?
    private var recovery: TunnelRecovery?
    private var expiry: Date?
    private var routingChanged = false
    private var policyRefresh: Task<Void, Never>?
    private var policyGeneration = 0
    private var receivedPolicy: String?

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        stateQueue.async {
            guard let config = AppIdentity.readTunnelConfig(), wdtt_engine_linked() != 0 else {
                let text = "Не удалось прочитать настройки VPN или запустить сетевой модуль"
                self.writeError(text)
                completionHandler(self.tunnelError(text))
                return
            }
            self.generation += 1
            self.startup = completionHandler
            TunnelBridge.setProvider(self)
            wdtt_set_output(silent_packet_out)
            wdtt_set_journal(silent_relay_event)
            self.startMonitoring()
            VPNLog.write(config.bootstrapDuration == nil ? "Запуск основного VPN" : "Запуск временного VPN")
            self.startEngine(config, previousAddress: nil) { result in
                switch result {
                case .success(let config):
                    self.activeConfig = config
                    self.recovery = TunnelRecovery(path: self.path, received: wdtt_received_bytes(), now: self.uptime)
                    let limit = config.paymentRouting == true ? 300 : 120
                    if let duration = config.bootstrapDuration, (1...limit).contains(duration) {
                        self.expiry = Date().addingTimeInterval(TimeInterval(duration))
                    }
                    self.finishStartup(nil)
                    wdtt_expand_workers()
                    self.startPolicyRefresh()
                case .failure(let error):
                    self.writeError(error.localizedDescription)
                    self.stopMonitoring()
                    TunnelBridge.setProvider(nil)
                    self.engineQueue.async { wdtt_stop() }
                    self.finishStartup(error)
                }
            }
        }
    }

    private var uptime: TimeInterval { ProcessInfo.processInfo.systemUptime }

    private func startEngine(
        _ config: TunnelConfig, previousAddress: String?, completion: @escaping (Result<TunnelConfig, Error>) -> Void
    ) {
        let token = generation
        let epoch = wdtt_start_epoch()
        let work = AppIdentity.workURL?.path ?? NSTemporaryDirectory()
        engineQueue.async {
            try? FileManager.default.createDirectory(atPath: work, withIntermediateDirectories: true)
            let code = config.hashes.joined(separator: ",").withCString { hashes in
                config.password.withCString { password in
                    config.deviceId.withCString { deviceId in
                        config.serverIP.withCString { ip in
                            work.withCString { dir in
                                wdtt_start(ip, Int32(config.serverPort), hashes, password, deviceId,
                                           Int32(config.workers), Int32(config.mtu), dir, epoch)
                            }
                        }
                    }
                }
            }
            let result: Result<String, Error>
            if code != 0 {
                var message = "Не удалось запустить сетевой модуль (код \(code))"
                if code == 6, let error = wdtt_last_error() {
                    message = String(cString: error)
                    free(error)
                }
                result = .failure(self.tunnelError(message))
            } else if let address = wdtt_assigned_address() {
                result = .success(String(cString: address))
                free(address)
            } else {
                result = .failure(self.tunnelError("Сервер не выдал адрес VPN"))
            }
            self.stateQueue.async {
                guard token == self.generation else { return }
                switch result {
                case .failure(let error): completion(.failure(error))
                case .success(let address):
                    var configured = config
                    configured.address = address
                    self.prepareEngine(configured, previousAddress: previousAddress, completion: completion)
                }
            }
        }
    }

    private func prepareEngine(
        _ config: TunnelConfig, previousAddress: String?, completion: @escaping (Result<TunnelConfig, Error>) -> Void
    ) {
        guard applyRussianPolicy(config.russian) else {
            completion(.failure(tunnelError("Не удалось применить правила российских сервисов")))
            return
        }
        VPNLog.write("Сервер выдал конфигурацию WireGuard", level: .success)
        let waitForHandshake = {
            self.handshake = (self.uptime + 15, { ready in
                if ready {
                    VPNLog.write("Рукопожатие WireGuard подтверждено", level: .success)
                    completion(.success(config))
                } else {
                    completion(.failure(self.tunnelError("Сервер не ответил на рукопожатие VPN")))
                }
            })
        }
        if previousAddress == config.address {
            waitForHandshake()
            return
        }
        let token = generation
        setTunnelNetworkSettings(makeSettings(config)) { error in
            self.stateQueue.async {
                guard token == self.generation else { return }
                if let error {
                    completion(.failure(error))
                } else {
                    if previousAddress == nil { self.readLoop(token: token) }
                    waitForHandshake()
                }
            }
        }
    }

    private func finishStartup(_ error: Error?) {
        let callback = startup
        startup = nil
        callback?(error)
    }

    private func startMonitoring() {
        let monitor = NWPathMonitor()
        self.monitor = monitor
        monitor.pathUpdateHandler = { [weak self] path in self?.networkChanged(path) }
        monitor.start(queue: stateQueue)
        let timer = DispatchSource.makeTimerSource(queue: stateQueue)
        timer.schedule(deadline: .now(), repeating: .milliseconds(500), leeway: .milliseconds(100))
        timer.setEventHandler { [weak self] in self?.tick() }
        self.timer = timer
        timer.resume()
    }

    private func stopMonitoring() {
        monitor?.cancel()
        monitor = nil
        timer?.cancel()
        timer = nil
        path = nil
        handshake = nil
        recovery = nil
        expiry = nil
        activeConfig = nil
        routingChanged = false
        policyRefresh?.cancel()
        policyRefresh = nil
        policyGeneration += 1
        receivedPolicy = nil
        reasserting = false
    }

    private func networkChanged(_ current: Network.NWPath) {
        let transport = current.usesInterfaceType(.wifi) ? "Wi-Fi" :
            current.usesInterfaceType(.cellular) ? "мобильная сеть" : "сеть"
        let interfaces = current.availableInterfaces.map(\.name).joined(separator: ",")
        let gateways = current.gateways.map { String(describing: $0) }.joined(separator: ",")
        let next = current.status == .satisfied ?
            "\(transport)|\(interfaces)|\(gateways)|\(current.supportsIPv4)|\(current.supportsIPv6)" : nil
        guard next != path else { return }
        path = next
        guard recovery != nil else { return }
        wdtt_reset_direct()
        recovery?.updatePath(next, received: next == nil ? 0 : wdtt_received_bytes(), now: uptime)
        reasserting = true
        VPNLog.write(next == nil ? "Сеть потеряна · ожидание" : "Сеть изменилась · \(transport)")
    }

    override func wake() {
        stateQueue.async {
            guard self.recovery != nil else { return }
            VPNLog.write("Пробуждение iOS · проверка WireGuard")
            self.recovery?.verify(now: self.uptime, received: wdtt_received_bytes())
            self.tick()
        }
    }

    private func tick() {
        if let expiry, expiry <= Date() {
            generation += 1
            wdtt_interrupt_start()
            stopMonitoring()
            TunnelBridge.setProvider(nil)
            engineQueue.async { wdtt_stop() }
            let text = "Время временного VPN истекло"
            writeError(text)
            cancelTunnelWithError(tunnelError(text))
            return
        }
        if let handshake {
            let ready = wdtt_handshake_stamp() != 0
            if ready || uptime >= handshake.until {
                self.handshake = nil
                handshake.done(ready)
            }
            return
        }
        guard !routingChanged, recovery?.hasNetwork == true,
              let action = recovery?.tick(now: uptime, received: wdtt_received_bytes()) else { return }
        switch action {
        case .probe: wdtt_probe()
        case .restart: restartTransport()
        case .recovered:
            if reasserting {
                reasserting = false
                VPNLog.write("WireGuard отвечает в текущей сети", level: .success)
            }
        }
    }

    private func restartTransport() {
        guard let config = activeConfig else { return }
        reasserting = true
        policyRefresh?.cancel()
        policyGeneration += 1
        receivedPolicy = nil
        VPNLog.write("Восстановление транспорта WDTT")
        startEngine(config, previousAddress: config.address) { result in
            let ready: Bool
            switch result {
            case .success(let updated):
                self.activeConfig = updated
                ready = true
            case .failure(let error):
                VPNLog.write("Повтор восстановления · \(error.localizedDescription)", level: .error)
                ready = false
                self.engineQueue.async { wdtt_stop() }
            }
            if self.recovery?.restartFinished(success: ready,
                                              received: wdtt_received_bytes(), now: self.uptime) == true {
                self.reasserting = false
                wdtt_expand_workers()
                self.startPolicyRefresh()
                VPNLog.write("Транспорт WDTT восстановлен", level: .success)
            }
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        stateQueue.async {
            VPNLog.write("Остановка расширения iOS: \(reason.rawValue)", level: reason == .userInitiated ? .info : .error)
            if reason != .userInitiated, reason != .none,
               AppIdentity.errorURL.map({ !FileManager.default.fileExists(atPath: $0.path) }) == true {
                self.writeError("iOS завершила VPN (код остановки \(reason.rawValue))")
            }
            self.generation += 1
            self.stopMonitoring()
            TunnelBridge.setProvider(nil)
            wdtt_interrupt_start()
            self.finishStartup(CancellationError())
            self.engineQueue.async {
                wdtt_stop()
                completionHandler()
            }
        }
    }

    private func readLoop(token: Int) {
        packetFlow.readPackets { [weak self] packets, _ in
            guard let self else { return }
            self.stateQueue.async {
                guard token == self.generation else { return }
                for packet in packets {
                    packet.withUnsafeBytes { raw in
                        guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return }
                        wdtt_input(base, Int32(packet.count))
                    }
                }
                self.readLoop(token: token)
            }
        }
    }

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        stateQueue.async {
            if messageData == Data("policy-received".utf8) {
                completionHandler?(self.receivedPolicy.map { Data($0.utf8) })
                return
            }
            guard messageData == Data("site-routing".utf8), !self.reasserting, !self.routingChanged,
                  var config = AppIdentity.readTunnelConfig(),
                  let previous = self.activeConfig, previous.bootstrapDuration == nil,
                  config.deviceId == previous.deviceId else {
                completionHandler?(nil)
                return
            }
            config.address = previous.address
            guard self.applyRussianPolicy(config.russian) else { completionHandler?(nil); return }
            let token = self.generation
            self.routingChanged = true
            self.setTunnelNetworkSettings(self.makeSettings(config)) { error in
                self.stateQueue.async {
                    guard token == self.generation else { completionHandler?(nil); return }
                    self.routingChanged = false
                    if error == nil {
                        self.activeConfig = config
                        self.receivedPolicy = nil
                        self.startPolicyRefresh()
                    } else {
                        _ = self.applyRussianPolicy(previous.russian)
                    }
                    completionHandler?(error == nil ? Data("ok".utf8) : nil)
                }
            }
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
        policyGeneration += 1
        guard activeConfig?.russian?.enabled == true else { return }
        let token = policyGeneration
        policyRefresh = Task { [weak self] in
            while !Task.isCancelled {
                let policy = await RussianServices.refresh()
                if let policy, !Task.isCancelled, let self {
                    self.stateQueue.async {
                        guard token == self.policyGeneration, !self.reasserting, !self.routingChanged,
                              self.activeConfig?.russian?.enabled == true else { return }
                        if policy.revision != self.activeConfig?.russian?.revision {
                            guard self.applyRussianPolicy(policy) else { return }
                            self.activeConfig?.russian = policy
                        }
                        self.receivedPolicy = policy.revision
                    }
                }
                do { try await Task.sleep(nanoseconds: policy == nil ? 30_000_000_000 : 300_000_000_000) }
                catch { return }
            }
        }
    }

    private func makeSettings(_ config: TunnelConfig) -> NEPacketTunnelNetworkSettings {
        let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: config.serverIP)
        let parsed = parseAddress(config.address)
        let ipv4 = NEIPv4Settings(addresses: [parsed.ip], subnetMasks: [parsed.mask])
        if config.bootstrapDuration != nil && config.paymentRouting != true {
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
