import Foundation

/// При активном VPN сначала шлюз туннеля; публичные адреса остаются резервом.
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

    static let tunnelAPI = "http://10.66.66.1:8000"

    static func bases(preferred: String, tunnelActive: Bool = false) -> [String] {
        var out: [String] = []
        func add(_ raw: String) {
            let v = rewriteStoredBase(raw)
            guard !v.isEmpty, !out.contains(v) else { return }
            if v.contains("132.243.234.162") || v.contains("132-243-234-162") { return }
            out.append(v)
        }
        if tunnelActive { out.append(tunnelAPI) }
        if !out.contains(hiveIpHttps) { out.append(hiveIpHttps) }
        cells.forEach { add($0) }
        add(hiveHttps)
        add(preferred)
        extraBases.forEach { add($0) }
        return out
    }

    static var extraBases: [String] = []

    static func timeoutSeconds(_ base: String) -> TimeInterval {
        _ = base
        return 8
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
