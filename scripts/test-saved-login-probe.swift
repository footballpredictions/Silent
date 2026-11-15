import Foundation

@main
struct SavedLoginProbeTest {
    static func main() async throws {
        let base = CommandLine.arguments[1]
        for path in ["ok", "expired", "unavailable", "slow"] {
            let started = Date()
            let result = try await SavedLoginProbe.fetch(url: URL(string: "\(base)/\(path)")!,
                                                        token: "fixture-token", appVersion: "fixture")
            let elapsed = Date().timeIntervalSince(started)
            precondition(elapsed < 5, "Saved login waited \(elapsed)s before bootstrap (\(path))")
            if path == "ok" {
                precondition(result == Data("{\"id\":\"fixture\"}".utf8))
                precondition(elapsed < 2, "A working direct route must not wait for bootstrap")
            } else {
                precondition(result == nil, "Unconfirmed login should defer to bootstrap (\(path))")
            }
            print("Saved login \(path): PASS (\(String(format: "%.2f", elapsed))s)")
        }
        let task = Task {
            try await SavedLoginProbe.fetch(url: URL(string: "\(base)/slow")!,
                                            token: "fixture-token", appVersion: nil)
        }
        task.cancel()
        do {
            _ = try await task.value
            preconditionFailure("Cancelled login was treated as a network fallback")
        } catch is CancellationError {}
        print("Saved login cancellation: PASS")
    }
}
