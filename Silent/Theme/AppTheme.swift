import Foundation
import SwiftUI
import UIKit

enum AppFont {
    static func text(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        let name: String
        switch weight {
        case .semibold, .bold, .heavy, .black:
            name = "Inter-SemiBold"
        case .medium:
            name = "Inter-Medium"
        default:
            name = "Inter-Regular"
        }
        if UIFont(name: name, size: size) != nil {
            return .custom(name, size: size)
        }
        return .system(size: size, weight: weight)
    }
}

enum ThemePalette {
    static func color(_ hex: String, fallback: Color = .black) -> Color {
        var hexStr = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        if hexStr.count == 6 { hexStr += "FF" }
        if hexStr.count == 8, let value = UInt64(hexStr, radix: 16) {
            let r = Double((value >> 24) & 0xFF) / 255
            let g = Double((value >> 16) & 0xFF) / 255
            let b = Double((value >> 8) & 0xFF) / 255
            let a = Double(value & 0xFF) / 255
            return Color(red: r, green: g, blue: b, opacity: a)
        }
        return fallback
    }

    static func assetURL(_ path: String) -> URL? {
        let raw = path.trimmingCharacters(in: .whitespacesAndNewlines)
        if raw.isEmpty { return nil }
        if raw.hasPrefix("http://") || raw.hasPrefix("https://") { return URL(string: raw) }
        if raw.hasPrefix("/") { return URL(string: PublicApiFailover.hiveHttps + raw) }
        return nil
    }
}

struct Palette {
    var bg: Color
    var fg: Color
    var on: Color
    var off: Color
    var link: Color
    var dark: Bool

    static func resolve(theme: ThemeData?, dark: Bool) -> Palette {
        let t = theme ?? ThemeData()
        if dark {
            let bg = t.dark_background_color.isEmpty ? ThemePalette.color(t.text_color) : ThemePalette.color(t.dark_background_color)
            let fg = t.dark_text_color.isEmpty ? ThemePalette.color(t.background_color, fallback: .white) : ThemePalette.color(t.dark_text_color)
            let on = t.dark_toggle_on_color.isEmpty ? fg : ThemePalette.color(t.dark_toggle_on_color)
            let off = t.dark_toggle_off_color.isEmpty ? fg.opacity(0.35) : ThemePalette.color(t.dark_toggle_off_color)
            let link = t.dark_login_link_color.isEmpty ? ThemePalette.color(t.login_link_color, fallback: Color(red: 0.27, green: 0.5, blue: 0.76)) : ThemePalette.color(t.dark_login_link_color)
            return Palette(bg: bg, fg: fg, on: on, off: off, link: link, dark: true)
        }
        return Palette(
            bg: ThemePalette.color(t.background_color, fallback: .white),
            fg: ThemePalette.color(t.text_color, fallback: .black),
            on: ThemePalette.color(t.toggle_on_color, fallback: .black),
            off: ThemePalette.color(t.toggle_off_color, fallback: Color(white: 0.8)),
            link: ThemePalette.color(t.login_link_color, fallback: Color(red: 0.27, green: 0.5, blue: 0.76)),
            dark: false
        )
    }
}

enum LocalStore {
    private static let d = UserDefaults.standard
    private static let siteExclusions = SiteExclusionsStore(defaults: d)

    static var appearanceDark: Bool {
        get { d.bool(forKey: "appearance_dark") }
        set { d.set(newValue, forKey: "appearance_dark") }
    }
    static var rememberMe: Bool {
        get { d.bool(forKey: "remember_me") }
        set { d.set(newValue, forKey: "remember_me") }
    }
    static var rememberedEmail: String {
        get { d.string(forKey: "remembered_email") ?? "" }
        set { d.set(newValue, forKey: "remembered_email") }
    }
    static var rememberedPassword: String {
        get { KeychainHelper.get("remembered_password") ?? "" }
        set {
            if newValue.isEmpty { KeychainHelper.delete("remembered_password") }
            else { KeychainHelper.set(newValue, key: "remembered_password") }
        }
    }
    static var dnsPreset: String {
        get { d.string(forKey: "dns_preset") ?? "server" }
        set { d.set(newValue, forKey: "dns_preset") }
    }
    static var customDns: String {
        get { d.string(forKey: "dns_custom") ?? "" }
        set { d.set(newValue, forKey: "dns_custom") }
    }
    static var preferredServer: String {
        get {
            let raw = (d.string(forKey: "preferred_server") ?? "server1").lowercased()
            if raw.isEmpty || raw == "queen" || raw == "main" { return "server1" }
            return raw
        }
        set { d.set(newValue, forKey: "preferred_server") }
    }
    static var siteRules: [String] {
        get { siteExclusions.load().activeRules }
        set { siteExclusions.save(rules: newValue, whitelist: siteExclusions.load().whitelist) }
    }
    static var sitesWhitelist: Bool {
        get { siteExclusions.load().whitelist }
        set { siteExclusions.switchMode(newValue) }
    }
}

enum DnsInput {
    static func sanitize(_ raw: String) -> [String]? {
        let parts = raw.split { $0 == "," || $0 == " " || $0 == ";" }.map { String($0).trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        if parts.isEmpty { return nil }
        if parts.count > 3 { return nil }
        let ok = parts.allSatisfy { isIP($0) }
        return ok ? parts : nil
    }

    static func isIP(_ s: String) -> Bool {
        if s.contains(":") { return s.count >= 3 }
        let bits = s.split(separator: ".")
        guard bits.count == 4 else { return false }
        return bits.allSatisfy { Int($0).map { (0...255).contains($0) } ?? false }
    }
}

extension String {
    var nilIfEmpty: String? {
        let t = trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }
}
