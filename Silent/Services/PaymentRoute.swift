import Foundation

enum PaymentRoute {
    static let site = URL(string: "https://yoomoney.ru/")!

    static func isCheckoutURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host?.lowercased() == site.host &&
            url.user == nil && url.password == nil && (url.port == nil || url.port == 443)
    }

    static func check() async -> Bool {
        await PaymentConnectivity.check(host: site.host!)
    }

    /// Connected/handshake can precede propagation of the app's DNS and routes.
    @MainActor
    static func waitUntilReady(attempts: Int, delayNanoseconds: UInt64 = 250_000_000,
                               check: () async throws -> Bool) async throws -> Bool {
        for attempt in 0..<max(0, attempts) {
            try Task.checkCancellation()
            if try await check() { return true }
            if attempt + 1 < attempts { try await Task.sleep(nanoseconds: delayNanoseconds) }
        }
        return false
    }

    @MainActor
    static func choose<Route>(_ routes: [Route], start: (Route) async throws -> Void,
                              probe: () async throws -> Bool, stop: () async -> Bool) async throws -> Int? {
        for (index, route) in routes.enumerated() {
            try Task.checkCancellation()
            do {
                try await start(route)
            } catch {
                try Task.checkCancellation()
                guard await stop() else { return nil }
                continue
            }
            if try await probe() {
                try Task.checkCancellation()
                return index
            }
            try Task.checkCancellation()
            guard await stop() else { return nil }
        }
        return nil
    }

}
