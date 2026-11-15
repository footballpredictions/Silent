import Foundation

/// A read-only shortcut before starting bootstrap. Token refresh belongs to the
/// normal API path after bootstrap, so it cannot extend this launch deadline.
enum SavedLoginProbe {
    static let timeout: TimeInterval = 3

    static func fetch(url: URL, token: String, appVersion: String?,
                      configuration: URLSessionConfiguration = .ephemeral) async throws -> Data? {
        configuration.timeoutIntervalForRequest = timeout
        configuration.timeoutIntervalForResource = timeout
        configuration.waitsForConnectivity = false
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: url, timeoutInterval: timeout)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let appVersion { request.setValue(appVersion, forHTTPHeaderField: "X-App-Version") }
        do {
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
            guard let response = response as? HTTPURLResponse, response.statusCode == 200 else { return nil }
            return data
        } catch {
            try Task.checkCancellation()
            return nil
        }
    }
}
