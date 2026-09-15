import Foundation

/// Публичный API: сначала Улей, соты :9100 по очереди если Улей не ответил.
enum PublicApiFailover {
    static let hiveHttps = "https://132-243-234-162.nip.io"
    static let hiveIpHttps = "https://132.243.234.162"
    static let cells = [
        "http://87.58.213.193:9100",
        "http://78.17.74.27:9100",
    ]

    static func bases(preferred: String) -> [String] {
        var out: [String] = []
        func add(_ raw: String) {
            let v = raw.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            guard !v.isEmpty, !out.contains(v) else { return }
            out.append(v)
        }
        add(preferred)
        add(hiveHttps)
        add(hiveIpHttps)
        cells.forEach { add($0) }
        return out
    }

    static func timeoutSeconds(_ base: String) -> TimeInterval {
        if base.contains(":9100") { return 8 }
        return 4
    }
}
