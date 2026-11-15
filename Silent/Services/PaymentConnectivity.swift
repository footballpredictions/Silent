import Darwin
import Foundation
import Network
import Security

/// Try every DNS address. A TCP connection to one address can succeed while its
/// TLS handshake stalls; that must not reject another working address on the exit.
enum PaymentConnectivity {
    static func check(host: String) async -> Bool {
        let addresses = await resolveIPv4(host)
        return await anyReachable(addresses) { address in
            await checkHTTPS(address: address, host: host)
        }
    }

    static func anyReachable(_ addresses: [String], check: @escaping (String) async -> Bool) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            for address in Array(Set(addresses)).prefix(8) {
                group.addTask {
                    guard !Task.isCancelled else { return false }
                    return await check(address)
                }
            }
            while let ready = await group.next() {
                if ready { group.cancelAll(); return true }
            }
            return false
        }
    }

    static func accepts(_ response: Data) -> Bool {
        guard let line = String(data: response, encoding: .utf8)?.components(separatedBy: "\r\n").first,
              line.hasPrefix("HTTP/1."), let code = line.split(separator: " ").dropFirst().first.flatMap({ Int($0) }) else { return false }
        return (200...399).contains(code)
    }

    private static func resolveIPv4(_ host: String) async -> [String] {
        let result = PaymentProbeResult<[String]>()
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                result.wait { continuation.resume(returning: $0) }
                DispatchQueue.global(qos: .utility).async {
                    var hints = addrinfo()
                    hints.ai_family = AF_INET
                    hints.ai_socktype = SOCK_STREAM
                    var first: UnsafeMutablePointer<addrinfo>?
                    guard getaddrinfo(host, "443", &hints, &first) == 0 else { result.finish([]); return }
                    defer { if let first { freeaddrinfo(first) } }
                    var values: [String] = []
                    var entry = first
                    while let item = entry, values.count < 8 {
                        var value = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                        if getnameinfo(item.pointee.ai_addr, item.pointee.ai_addrlen, &value,
                                       socklen_t(value.count), nil, 0, NI_NUMERICHOST) == 0 {
                            values.append(String(cString: value))
                        }
                        entry = item.pointee.ai_next
                    }
                    result.finish(values)
                }
                DispatchQueue.global().asyncAfter(deadline: .now() + 3) { result.finish([]) }
            }
        }, onCancel: { result.finish([]) })
    }

    private static func checkHTTPS(address: String, host: String) async -> Bool {
        guard !Task.isCancelled else { return false }
        let tls = NWProtocolTLS.Options()
        // Network.framework uses this name for SNI AND certificate validation.
        host.withCString { sec_protocol_options_set_tls_server_name(tls.securityProtocolOptions, $0) }
        sec_protocol_options_add_tls_application_protocol(tls.securityProtocolOptions, "http/1.1")
        let connection = NWConnection(host: NWEndpoint.Host(address), port: .https,
                                      using: NWParameters(tls: tls, tcp: NWProtocolTCP.Options()))
        let queue = DispatchQueue(label: "silent.payment.https")
        let result = PaymentProbeResult<Bool>()
        let finish: (Bool) -> Void = { value in
            if result.finish(value) { connection.stateUpdateHandler = nil; connection.cancel() }
        }
        return await withTaskCancellationHandler(operation: {
            await withCheckedContinuation { continuation in
                result.wait { continuation.resume(returning: $0) }
                if Task.isCancelled { finish(false); return }
                var response = Data()
                func receive() {
                    connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) { data, _, complete, error in
                        if let data { response.append(data) }
                        if response.range(of: Data("\r\n".utf8)) != nil { finish(accepts(response)) }
                        else if error != nil || complete || response.count >= 8192 { finish(false) }
                        else { receive() }
                    }
                }
                connection.stateUpdateHandler = { state in
                    switch state {
                    case .ready:
                        let request = Data("HEAD / HTTP/1.1\r\nHost: \(host)\r\nConnection: close\r\nCache-Control: no-cache\r\n\r\n".utf8)
                        connection.send(content: request, completion: .contentProcessed { error in
                            if error != nil { finish(false) } else { receive() }
                        })
                    case .failed, .cancelled: finish(false)
                    default: break
                    }
                }
                connection.start(queue: queue)
                queue.asyncAfter(deadline: .now() + 4) { finish(false) }
            }
        }, onCancel: { finish(false) })
    }
}

private final class PaymentProbeResult<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false
    private var value: Value?
    private var callback: ((Value) -> Void)?

    func wait(_ callback: @escaping (Value) -> Void) {
        lock.lock()
        if completed {
            let value = value!
            lock.unlock()
            callback(value)
        } else {
            self.callback = callback
            lock.unlock()
        }
    }

    @discardableResult
    func finish(_ value: Value) -> Bool {
        lock.lock()
        guard !completed else { lock.unlock(); return false }
        completed = true
        self.value = value
        let callback = callback
        self.callback = nil
        lock.unlock()
        callback?(value)
        return true
    }
}
