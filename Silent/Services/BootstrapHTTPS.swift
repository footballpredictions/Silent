import Foundation
import Network
import Security

/// Fixed-host HTTPS fallback when the resolver cannot reach nip.io. The socket
/// uses an IP, but SNI, certificate verification and Host use the same DNS name.
enum BootstrapHTTPS {
    static func post(_ body: Data, port: UInt16) async throws -> (status: Int, body: Data) {
        guard let endpointPort = NWEndpoint.Port(rawValue: port) else { throw URLError(.badURL) }
        let host = PublicApiFailover.hiveHost
        let tls = NWProtocolTLS.Options()
        host.withCString { sec_protocol_options_set_tls_server_name(tls.securityProtocolOptions, $0) }
        sec_protocol_options_set_min_tls_protocol_version(tls.securityProtocolOptions, .TLSv12)
        let parameters = NWParameters(tls: tls, tcp: NWProtocolTCP.Options())
        let connection = NWConnection(host: NWEndpoint.Host(PublicApiFailover.hiveIP), port: endpointPort, using: parameters)
        let authority = port == 443 ? host : "\(host):\(port)"
        let head = "POST /api/vpn/bootstrap-config HTTP/1.0\r\nHost: \(authority)\r\nContent-Type: application/json\r\nContent-Length: \(body.count)\r\nConnection: close\r\n\r\n"
        var request = Data(head.utf8)
        request.append(body)
        let transfer = Transfer(connection: connection, request: request)
        return try await withTaskCancellationHandler(operation: {
            try await transfer.run()
        }, onCancel: {
            transfer.cancel()
        })
    }

    private final class Transfer: @unchecked Sendable {
        private let queue = DispatchQueue(label: "silent.bootstrap.https")
        private let connection: NWConnection
        private let request: Data
        private var received = Data()
        private var reply: CheckedContinuation<(Int, Data), Error>?
        private var cancelled = false

        init(connection: NWConnection, request: Data) {
            self.connection = connection
            self.request = request
        }

        func run() async throws -> (Int, Data) {
            try await withCheckedThrowingContinuation { continuation in
                queue.async {
                    guard !self.cancelled else { continuation.resume(throwing: CancellationError()); return }
                    self.reply = continuation
                    self.connection.stateUpdateHandler = { [weak self] state in
                        guard let self else { return }
                        switch state {
                        case .ready:
                            self.connection.send(content: self.request, completion: .contentProcessed { [weak self] error in
                                if let error { self?.finish(.failure(error)) }
                                else { self?.receive() }
                            })
                        case .failed(let error): self.finish(.failure(error))
                        case .cancelled: self.finish(.failure(CancellationError()))
                        default: break
                        }
                    }
                    self.connection.start(queue: self.queue)
                    self.queue.asyncAfter(deadline: .now() + 5) { [weak self] in
                        self?.finish(.failure(URLError(.timedOut)))
                    }
                }
            }
        }

        func cancel() {
            queue.async {
                self.cancelled = true
                self.finish(.failure(CancellationError()))
            }
        }

        private func receive() {
            guard reply != nil else { return }
            connection.receive(minimumIncompleteLength: 1, maximumLength: 16 * 1024) { [weak self] data, _, complete, error in
                guard let self, self.reply != nil else { return }
                if let error { self.finish(.failure(error)); return }
                if let data { self.received.append(data) }
                guard self.received.count <= 256 * 1024 else {
                    self.finish(.failure(URLError(.dataLengthExceedsMaximum))); return
                }
                do {
                    if let response = try BootstrapHTTPResponse.parse(self.received, complete: complete) {
                        self.finish(.success(response))
                    } else {
                        self.receive()
                    }
                } catch {
                    self.finish(.failure(error))
                }
            }
        }

        private func finish(_ result: Result<(Int, Data), Error>) {
            guard let reply else { return }
            self.reply = nil
            connection.stateUpdateHandler = nil
            connection.cancel()
            reply.resume(with: result)
        }
    }
}
