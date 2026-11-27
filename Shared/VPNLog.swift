import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

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
    struct Snapshot {
        let sessionID: UUID?
        let entries: [VPNLogEntry]
    }

    static let sessionOption = "silent-log-session"
    private static let maxSize: UInt64 = 192 * 1024
    private static let protection: Data.WritingOptions = [.atomic, .completeFileProtectionUntilFirstUserAuthentication]

    private static func withJournal<T>(_ action: (URL) -> T) -> T? {
        guard let directory = AppIdentity.groupURL else { return nil }
        let descriptor = open(directory.appendingPathComponent("vpn-events.lock").path, O_CREAT | O_RDWR, mode_t(0o600))
        guard descriptor >= 0 else { return nil }
        defer { _ = close(descriptor) }
        // The app and the Network Extension run in different processes.
        while flock(descriptor, LOCK_EX) != 0 {
            guard errno == EINTR else { return nil }
        }
        return action(directory)
    }

    private static func sessionFile(in directory: URL) -> URL {
        directory.appendingPathComponent("vpn-events.session")
    }

    private static func journalFile(in directory: URL) -> URL {
        directory.appendingPathComponent("vpn-events.jsonl")
    }

    private static func sessionID(in directory: URL) -> UUID? {
        (try? String(contentsOf: sessionFile(in: directory), encoding: .utf8)).flatMap(UUID.init(uuidString:))
    }

    static func currentSessionID() -> UUID? { withJournal { sessionID(in: $0) } ?? nil }

    static func beginSession() -> UUID? {
        withJournal { directory -> UUID? in
            let id = UUID()
            let file = journalFile(in: directory)
            do {
                if FileManager.default.fileExists(atPath: file.path) {
                    try FileManager.default.removeItem(at: file)
                }
                try Data(id.uuidString.utf8).write(to: sessionFile(in: directory), options: protection)
                return id
            } catch { return nil }
        } ?? nil
    }

    // Only explicitly selected events go into the shareable journal.
    static func write(_ message: String, level: VPNLogLevel = .info, source: String = "Туннель",
                      key: String? = nil, sessionID owner: UUID?) {
        guard var data = try? JSONEncoder().encode(
            VPNLogEntry(date: Date(), level: level, source: source, message: message, key: key)
        ) else { return }
        data.append(10)
        _ = withJournal { directory in
            guard sessionID(in: directory) == owner else { return }
            let file = journalFile(in: directory)
            let fm = FileManager.default
            let size = (try? fm.attributesOfItem(atPath: file.path)[.size] as? NSNumber)?.uint64Value ?? 0
            if size >= maxSize {
                let recent = (try? Data(contentsOf: file))?.suffix(Int(maxSize / 2)) ?? Data()
                var retained = recent.firstIndex(of: 10).map { Data(recent.suffix(from: recent.index(after: $0))) } ?? Data()
                retained.append(data)
                try? retained.write(to: file, options: protection)
            } else if !fm.fileExists(atPath: file.path) {
                try? data.write(to: file, options: protection)
            } else if let handle = try? FileHandle(forWritingTo: file) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            }
        }
    }

    static func read() -> Snapshot {
        guard let (id, data) = withJournal({ directory in
            (sessionID(in: directory), try? Data(contentsOf: journalFile(in: directory)))
        }) else { return Snapshot(sessionID: nil, entries: []) }
        guard let data, data.count <= maxSize + 4096 else { return Snapshot(sessionID: id, entries: []) }
        let decoder = JSONDecoder()
        let entries = data.split(separator: 10).suffix(1200).compactMap {
            try? decoder.decode(VPNLogEntry.self, from: Data($0))
        }
        return Snapshot(sessionID: id, entries: entries)
    }

    static func clear() {
        _ = withJournal { directory in
            try? FileManager.default.removeItem(at: journalFile(in: directory))
        }
    }
}
