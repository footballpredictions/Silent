import Foundation

/// Публичный API: сначала живые соты :9100, Улей :443 последним (его режут из РФ).
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
        cells.forEach { add($0) }
        add(preferred)
        add(hiveHttps)
        add(hiveIpHttps)
        return out
    }

    static func timeoutSeconds(_ base: String) -> TimeInterval {
        if base.contains(":9100") { return 8 }
        return 4
    }

    static func shouldTryNextBase(httpCode: Int) -> Bool {
        if httpCode == 0 || httpCode == 408 || httpCode >= 500 { return true }
        return false
    }
}

enum EmailConfirmationPolicy {
    static func skipConfirmation(themeSkip: Bool, requiredFlag: String?) -> Bool {
        if themeSkip { return true }
        return requiredFlag?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "false"
    }
}
