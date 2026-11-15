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
        let time = date.formatted(date: .omitted, time: .standard)
        let label = source == "WDTT" && message.hasPrefix("[") ? message : "[\(source)] \(message)"
        return "\(time) \(label)"
    }
}

struct VPNLogRow: Identifiable {
    let id: UUID
    var entry: VPNLogEntry
    var count: Int
    var line: String { count == 1 ? entry.line : "\(entry.line) (×\(count))" }

    private struct Event: Hashable {
        let source: String
        let level: VPNLogLevel
        let name: String
    }

    private static let relayStage = try! NSRegularExpression(pattern: #"^(Воркер|Группа) №[0-9]+ · "#)
    private static let workerState = try! NSRegularExpression(pattern: #"^Воркер №[0-9]+ (активен|отключён) · "#)
    private static let metric = try! NSRegularExpression(pattern: #"(?i)(?<![\p{L}\p{N}.])[0-9]+(?:[.,][0-9]+)?(?=\s*(?:%|(?:МБ|КБ|ГБ|мс|с|сек|Мбит/с)\b))"#)
    private static let counter = try! NSRegularExpression(pattern: #"(?i)\b(активных(?: каналов)?|задач|воркеров|потоков|хешей)\s*[:=]\s*[0-9]+(?:/[0-9]+)?"#)
    private static let stageID = try! NSRegularExpression(pattern: #"(\[(?:ГРУППА|ВОРКЕР|РЕТРАНСЛЯТОР) #)[0-9]+(\])"#)
    private static let workerRange = try! NSRegularExpression(pattern: #"(Запуск воркеров )[0-9]+[–-][0-9]+"#)

    private static func eventName(_ message: String) -> String {
        if message.hasPrefix("[СТАТИСТИКА]") { return "stats" }
        if message.hasPrefix("[РЕСУРСЫ]") { return "resources" }
        // Normalize changing values only in the key. Keep the entire latest
        // message on screen and in copied logs; distinct error codes stay apart.
        var key = message
        for (regex, replacement) in [(metric, "~"), (counter, "$1: ~"),
                                      (stageID, "$1~$2"), (workerRange, "$1~")] {
            key = regex.stringByReplacingMatches(in: key, range: NSRange(key.startIndex..., in: key), withTemplate: replacement)
        }
        return key
    }

    private static func displayEntry(_ entry: VPNLogEntry) -> VPNLogEntry {
        guard entry.source == "WDTT" else { return entry }
        let message = entry.message
        let range = NSRange(location: 0, length: message.utf16.count)
        let stage = relayStage.stringByReplacingMatches(in: message, range: range, withTemplate: "")
        let state = workerState.stringByReplacingMatches(in: message, range: range, withTemplate: "Воркер $1 · ")
        var key = eventName(stage)
        var display = stage
        if state != message {
            key = String(state.prefix(while: { $0 != "·" }))
            display = state
        }
        return VPNLogEntry(id: entry.id, date: entry.date, level: entry.level, source: entry.source, message: display, key: key)
    }

    static func grouped(_ entries: [VPNLogEntry]) -> [Self] {
        var rows: [Self] = []
        var indexes: [Event: Int] = [:]
        for rawEntry in entries.sorted(by: { $0.date < $1.date }) {
            let entry = displayEntry(rawEntry)
            let key = Event(source: entry.source, level: entry.level, name: entry.key ?? eventName(entry.message))
            if let index = indexes[key] {
                rows[index].entry = entry
                rows[index].count += 1
            } else {
                indexes[key] = rows.count
                rows.append(Self(id: entry.id, entry: entry, count: 1))
            }
        }
        return rows.sorted { $0.entry.date < $1.entry.date }
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
