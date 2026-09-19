import Foundation

/// Публичный API: сначала живые соты :9100, Улей :443 последним (его режут из РФ).
enum PublicApiFailover {
    static let hiveHttps = "https://89-125-188-100.nip.io"
    static let hiveIpHttps = "https://89.125.188.100"
    static let cells = [
        "http://87.58.213.193:9100",
        "http://78.17.74.27:9100",
    ]

    static func rewriteStoredBase(_ raw: String, currentNip: String = hiveHttps) -> String {
        let stored = raw.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if stored.isEmpty { return currentNip }
        let host = URL(string: stored)?.host?.lowercased()
            ?? stored.replacingOccurrences(of: "https://", with: "")
                .replacingOccurrences(of: "http://", with: "")
                .split(separator: "/").first.map(String.init)?.lowercased()
        if host == "132.243.234.162" || host == "132-243-234-162.nip.io" { return currentNip }
        if host == "89.125.188.100" { return currentNip }
        return stored
    }

    static func bases(preferred: String) -> [String] {
        var out: [String] = []
        func add(_ raw: String) {
            let v = rewriteStoredBase(raw)
            guard !v.isEmpty, !out.contains(v) else { return }
            if v.contains("132.243.234.162") || v.contains("132-243-234-162") { return }
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
