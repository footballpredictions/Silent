import Darwin
import Foundation
import NetworkExtension

enum TunnelBridge {
    static weak var provider: PacketTunnelProvider?
}

@_cdecl("silent_packet_out")
func silent_packet_out(_ data: UnsafePointer<UInt8>?, _ len: Int32) {
    guard let data, len > 0, let provider = TunnelBridge.provider else { return }
    let buf = Data(bytes: data, count: Int(len))
    let proto: NSNumber = (buf.first ?? 0) >> 4 == 6 ? 30 : 2
    provider.packetFlow.writePackets([buf], withProtocols: [proto])
}

class PacketTunnelProvider: NEPacketTunnelProvider {
    private var reading = false
    private var activeConfig: TunnelConfig?
    private var policyRefresh: Task<Void, Never>?

    override func startTunnel(options: [String: NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        TunnelBridge.provider = self
        guard let config = loadConfig() else {
            completionHandler(tunnelError("Нет конфига туннеля"))
            return
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
        let code = config.hashes.joined(separator: ",").withCString { hashes in
            config.password.withCString { password in
                config.deviceId.withCString { deviceId in
                    config.privateKey.withCString { priv in
                        config.publicKey.withCString { pub in
                            config.serverIP.withCString { ip in
                                work.withCString { dir in
                                    wdtt_start(ip, Int32(config.serverPort), hashes, password, deviceId, Int32(config.workers), priv, pub, Int32(config.mtu), dir)
                                }
                            }
                        }
                    }
                }
            }
        }
        if code != 0 {
            let raw = String(cString: wdtt_last_error())
            wdtt_stop()
            writeError(raw)
            completionHandler(tunnelError(raw))
            return
        }

        guard applyRussianPolicy(config.russian) else {
            wdtt_stop()
            completionHandler(tunnelError("Не удалось применить российские сервисы"))
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
            self?.startPolicyRefresh()
            completionHandler(nil)
        }
    }

    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        reading = false
        policyRefresh?.cancel()
        policyRefresh = nil
        activeConfig = nil
        wdtt_stop()
        TunnelBridge.provider = nil
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
        guard let url = AppIdentity.configURL, let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(TunnelConfig.self, from: data)
    }

    override func handleAppMessage(_ messageData: Data, completionHandler: ((Data?) -> Void)?) {
        guard messageData == Data("site-routing".utf8), let config = loadConfig() else {
            completionHandler?(nil)
            return
        }
        let previous = activeConfig
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
        guard let url = AppIdentity.errorURL else { return }
        try? text.write(to: url, atomically: true, encoding: .utf8)
    }

    private func tunnelError(_ text: String) -> NSError {
        NSError(domain: "SilentVPN", code: 1, userInfo: [NSLocalizedDescriptionKey: text])
    }
}
