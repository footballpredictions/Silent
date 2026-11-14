import Foundation

enum VPNLogLevel: String, Codable { case info, success, error }

struct VPNLogEntry: Identifiable, Codable {
    var id = UUID()
    let date: Date
    let level: VPNLogLevel
    let source: String
    let message: String
    var key: String? = nil

    var line: String {
        "\(date.formatted(date: .omitted, time: .standard)) [\(source)] \(message)"
    }
}

struct VPNLogRow: Identifiable {
    let id: UUID
    var entry: VPNLogEntry
    var count: Int
    var line: String { count == 1 ? entry.line : "\(entry.line) (×\(count))" }

    static func grouped(_ entries: [VPNLogEntry]) -> [Self] {
        var rows: [Self] = []
        var indexes: [String: Int] = [:]
        for entry in entries.sorted(by: { $0.date < $1.date }) {
            let key = "\(entry.source)|\(entry.level.rawValue)|\(entry.key ?? entry.message)"
            if let index = indexes[key] {
                rows[index].entry = entry
                rows[index].count += 1
            } else {
                indexes[key] = rows.count
                rows.append(Self(id: entry.id, entry: entry, count: 1))
            }
        }
        return rows
    }
}

enum VPNLog {
    private static var file: URL? { AppIdentity.groupURL?.appendingPathComponent("vpn-events.jsonl") }
    private static let lock = NSLock()
    private static let maxSize: UInt64 = 192 * 1024

    // Only explicitly selected events go into the shareable journal.
    static func write(_ message: String, level: VPNLogLevel = .info, source: String = "Туннель", key: String? = nil) {
        guard let file, var data = try? JSONEncoder().encode(
            VPNLogEntry(date: Date(), level: level, source: source, message: message, key: key)
        ) else { return }
        lock.lock()
        defer { lock.unlock() }
        data.append(10)
        let fm = FileManager.default
        let size = (try? fm.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.uint64Value ?? 0
        if size >= maxSize {
            let recent = (try? Data(contentsOf: file))?.suffix(Int(maxSize / 2)) ?? Data()
            var retained = recent.firstIndex(of: 10).map { Data(recent.suffix(from: recent.index(after: $0))) } ?? Data()
            retained.append(data)
            try? retained.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } else if !fm.fileExists(atPath: file.path) {
            try? data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        } else if let handle = try? FileHandle(forWritingTo: file) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        }
    }

    static func read() -> [VPNLogEntry] {
        guard let file, let data = try? Data(contentsOf: file), data.count <= maxSize + 4096 else { return [] }
        return data.split(separator: 10).suffix(1200).compactMap {
            try? JSONDecoder().decode(VPNLogEntry.self, from: Data($0))
        }
    }

    static func clear() {
        guard let file else { return }
        try? FileManager.default.removeItem(at: file)
    }
}
