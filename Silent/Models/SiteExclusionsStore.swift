import Foundation

/// Independent site lists. Legacy keys mirror the active mode for compatibility.
final class SiteExclusionsStore {
    struct State: Codable {
        var whitelist: Bool
        var blacklistRules: [String]
        var whitelistRules: [String]

        var activeRules: [String] { whitelist ? whitelistRules : blacklistRules }
    }

    private let defaults: UserDefaults
    private let key = "site_exclusions_v2"

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    func load() -> State {
        if let data = defaults.data(forKey: key),
           let state = try? JSONDecoder().decode(State.self, from: data) { return state }
        let mode = defaults.bool(forKey: "sites_whitelist")
        let legacy = defaults.stringArray(forKey: "site_rules") ?? []
        let state = State(whitelist: mode, blacklistRules: mode ? [] : legacy, whitelistRules: mode ? legacy : [])
        persist(state)
        return state
    }

    func save(rules: [String], whitelist: Bool) {
        var state = load()
        state.whitelist = whitelist
        if whitelist { state.whitelistRules = rules }
        else { state.blacklistRules = rules }
        persist(state)
    }

    func switchMode(_ whitelist: Bool) {
        var state = load()
        state.whitelist = whitelist
        persist(state)
    }

    private func persist(_ state: State) {
        guard let data = try? JSONEncoder().encode(state) else { return }
        // One canonical value keeps the selected mode and both lists together.
        defaults.set(data, forKey: key)
        defaults.set(state.activeRules, forKey: "site_rules")
        defaults.set(state.whitelist, forKey: "sites_whitelist")
    }
}
