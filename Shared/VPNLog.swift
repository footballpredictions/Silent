import Foundation

enum VPNLogLevel: String, Codable { case info, success, error }

struct VPNLogEntry: Identifiable, Codable {
    var id = UUID()
    let date: Date
    let level: VPNLogLevel
    let source: String
    let message: String

    var line: String {
        "\(date.formatted(date: .omitted, time: .standard)) [\(source)] \(message)"
    }
}

enum VPNLog {
    private static var file: URL? { AppIdentity.groupURL?.appendingPathComponent("vpn-events.jsonl") }
    private static let lock = NSLock()
    private static let maxSize: UInt64 = 96 * 1024

    // Only explicitly selected events go into the shareable journal.
    static func write(_ message: String, level: VPNLogLevel = .info, source: String = "Туннель") {
        guard let file, var data = try? JSONEncoder().encode(
            VPNLogEntry(date: Date(), level: level, source: source, message: message)
        ) else { return }
        lock.lock()
        defer { lock.unlock() }
        data.append(10)
        let fm = FileManager.default
        let size = (try? fm.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.uint64Value ?? 0
        if size >= maxSize || !fm.fileExists(atPath: file.path) {
            try? data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } else if let handle = try? FileHandle(forWritingTo: file) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        }
    }

    static func read() -> [VPNLogEntry] {
        guard let file, let data = try? Data(contentsOf: file), data.count <= maxSize + 4096 else { return [] }
        return data.split(separator: 10).suffix(200).compactMap {
            try? JSONDecoder().decode(VPNLogEntry.self, from: Data($0))
        }
    }

    static func clear() {
        guard let file else { return }
        try? FileManager.default.removeItem(at: file)
    }
}
