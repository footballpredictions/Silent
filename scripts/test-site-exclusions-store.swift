// On Mac:
// swiftc -parse-as-library Silent/Models/SiteExclusionsStore.swift scripts/test-site-exclusions-store.swift -o /tmp/silent-site-lists-test
// /tmp/silent-site-lists-test
import Foundation

@main
struct SiteListsTest {
    static func main() {
        for mode in [false, true] {
            let suite = "silent-site-lists-test-\(UUID().uuidString)"
            let defaults = UserDefaults(suiteName: suite)!
            defer { defaults.removePersistentDomain(forName: suite) }
            defaults.set(mode, forKey: "sites_whitelist")
            defaults.set(["2ip.io"], forKey: "site_rules")
            var store = SiteExclusionsStore(defaults: defaults)
            assert(store.load().activeRules == ["2ip.io"])
            store.switchMode(!mode)
            assert(store.load().activeRules.isEmpty)
            store.save(rules: ["mail.ru"], whitelist: !mode)
            store.switchMode(mode)
            assert(store.load().activeRules == ["2ip.io"])
            store.save(rules: [], whitelist: mode)
            store = SiteExclusionsStore(defaults: UserDefaults(suiteName: suite)!)
            assert(store.load().activeRules.isEmpty)
            for _ in 0..<5 {
                store.switchMode(!mode)
                assert(store.load().activeRules == ["mail.ru"])
                assert(defaults.stringArray(forKey: "site_rules") == ["mail.ru"])
                store.switchMode(mode)
                assert(store.load().activeRules.isEmpty)
            }
        }
        print("Site exclusions: migration, independent lists, clear and reload passed")
    }
}
