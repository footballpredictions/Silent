import Foundation

enum PaymentRoute {
    static let site = URL(string: "https://yoomoney.ru/")!

    static func isCheckoutURL(_ url: URL) -> Bool {
        url.scheme?.lowercased() == "https" && url.host?.lowercased() == site.host &&
            url.user == nil && url.password == nil && (url.port == nil || url.port == 443)
    }

    static func check() async -> Bool {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 4
        configuration.timeoutIntervalForResource = 5
        configuration.httpShouldSetCookies = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        configuration.urlCache = nil
        configuration.connectionProxyDictionary = [:]
        let session = URLSession(configuration: configuration, delegate: NoRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: site, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = "HEAD"
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        guard let (_, response) = try? await session.data(for: request),
              let http = response as? HTTPURLResponse, http.url == site else { return false }
        return (200...399).contains(http.statusCode)
    }

    @MainActor
    static func choose<Route>(_ routes: [Route], start: (Route) async throws -> Void,
                              probe: () async -> Bool, stop: () async -> Bool) async throws -> Int? {
        for (index, route) in routes.enumerated() {
            try Task.checkCancellation()
            do {
                try await start(route)
                if await probe() {
                    try Task.checkCancellation()
                    return index
                }
            } catch {
                try Task.checkCancellation()
            }
            try Task.checkCancellation()
            guard await stop() else { return nil }
        }
        return nil
    }

    private final class NoRedirect: NSObject, URLSessionTaskDelegate {
        func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                        newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
            completionHandler(nil)
        }
    }
}
