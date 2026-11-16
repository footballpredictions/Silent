import Foundation
import NetworkExtension

/// An extension's ordinary sockets use its physical path. Select the existing
/// tunnel explicitly for this private API, without replacing the VPN profile.
enum PolicyTunnelHTTP {
    static func fetch(through provider: NEPacketTunnelProvider) async throws -> Data {
        guard !Task.isCancelled else { throw CancellationError() }
        // This API remains available on the deployment target (iOS 16). Its
        // iOS 18 replacement requires NWParameters.requiredInterface to be set
        // to provider.virtualInterface, rather than an ordinary NWConnection.
        let connection = provider.createTCPConnectionThroughTunnel(
            to: NWHostEndpoint(hostname: "10.66.66.1", port: "8000"),
            enableTLS: false, tlsParameters: nil, delegate: nil
        )
        let transfer = Transfer(connection: connection)
        return try await withTaskCancellationHandler(operation: {
            try await transfer.run()
        }, onCancel: {
            transfer.cancel()
        })
    }

    private final class Transfer: @unchecked Sendable {
        private let queue = DispatchQueue(label: "silent.policy.tunnel-http")
        private let connection: NWTCPConnection
        private var observation: NSKeyValueObservation?
        private var reply: CheckedContinuation<Data, Error>?
        private var received = Data()
        private var sent = false
        private var cancelled = false

        init(connection: NWTCPConnection) { self.connection = connection }

        func run() async throws -> Data {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    guard !self.cancelled else {
                        self.connection.cancel()
                        continuation.resume(throwing: CancellationError())
                        return
                    }
                    self.reply = continuation
                    self.observation = self.connection.observe(\.state, options: [.initial, .new]) { [weak self] connection, _ in
                        let state = connection.state
                        self?.queue.async { [weak self] in self?.stateChanged(state) }
                    }
                    self.queue.asyncAfter(deadline: .now() + 3) { [weak self] in
                        self?.finish(.failure(URLError(.timedOut)))
                    }
                }
            }
        }

        func cancel() {
            queue.async {
                self.cancelled = true
                self.connection.cancel()
                self.finish(.failure(CancellationError()))
            }
        }

        private func stateChanged(_ state: NWTCPConnectionState) {
            guard reply != nil else { return }
            switch state {
            case .connected:
                guard !sent else { return }
                sent = true
                let request = Data("GET /api/vpn/routing-policy HTTP/1.0\r\nHost: 10.66.66.1:8000\r\nConnection: close\r\nCache-Control: no-cache\r\n\r\n".utf8)
                connection.write(request) { [weak self] error in
                    self?.queue.async { [weak self] in
                        guard let self, self.reply != nil else { return }
                        if let error { self.finish(.failure(error)) }
                        else { self.receive() }
                    }
                }
            case .cancelled, .invalid:
                finish(.failure(URLError(.cannotConnectToHost)))
            case .disconnected:
                // Once reading, consume the final read callback before judging
                // a close-delimited HTTP response. The deadline bounds silence.
                if !sent { finish(.failure(URLError(.cannotConnectToHost))) }
            default: break
            }
        }

        private func receive() {
            guard reply != nil else { return }
            connection.readMinimumLength(1, maximumLength: 16 * 1024) { [weak self] data, error in
                self?.queue.async { [weak self] in
                    guard let self, self.reply != nil else { return }
                    if let error { self.finish(.failure(error)); return }
                    if let data { self.received.append(data) }
                    do {
                        if let body = try PolicyHTTPResponse.parse(self.received, complete: data?.isEmpty != false) {
                            self.finish(.success(body))
                        } else {
                            self.receive()
                        }
                    } catch { self.finish(.failure(error)) }
                }
            }
        }

        private func finish(_ result: Result<Data, Error>) {
            guard let reply else { return }
            self.reply = nil
            observation?.invalidate()
            observation = nil
            connection.cancel()
            reply.resume(with: result)
        }
    }
}

enum PolicyHTTPResponse {
    static func parse(_ data: Data, complete: Bool) throws -> Data? {
        let headerLimit = 16 * 1024
        let bodyLimit = 256 * 1024
        guard data.count <= headerLimit + 4 + bodyLimit else { throw URLError(.dataLengthExceedsMaximum) }
        guard let boundary = data.range(of: Data([13, 10, 13, 10])) else {
            if complete || data.count >= headerLimit { throw URLError(.badServerResponse) }
            return nil
        }
        let header = data[..<boundary.lowerBound]
        guard header.count < headerLimit, let text = String(data: header, encoding: .utf8) else {
            throw URLError(.badServerResponse)
        }
        let lines = text.components(separatedBy: "\r\n")
        let status = lines[0].split(separator: " ", maxSplits: 2)
        guard status.count >= 2, ["HTTP/1.0", "HTTP/1.1"].contains(String(status[0])), status[1] == "200" else {
            throw URLError(.badServerResponse)
        }
        var length: Int?
        for line in lines.dropFirst() {
            let pair = line.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
            guard pair.count == 2 else { throw URLError(.badServerResponse) }
            switch pair[0].lowercased() {
            case "transfer-encoding": throw URLError(.badServerResponse)
            case "content-length":
                guard length == nil, let value = Int(pair[1].trimmingCharacters(in: .whitespaces)),
                      (0...bodyLimit).contains(value) else { throw URLError(.badServerResponse) }
                length = value
            default: break
            }
        }
        let body = data[boundary.upperBound...]
        guard body.count <= bodyLimit else { throw URLError(.dataLengthExceedsMaximum) }
        if let length {
            if body.count == length { return Data(body) }
            if body.count > length || complete { throw URLError(.badServerResponse) }
        } else if complete {
            return Data(body)
        }
        return nil
    }
}
