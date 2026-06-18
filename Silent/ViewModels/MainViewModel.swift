import SwiftUI
import Combine

@MainActor
class MainViewModel: ObservableObject {
    @Published var vpnState: VpnState = .disconnected
    @Published var profile: UserProfile?
    @Published var theme: ThemeData?
    @Published var errorMessage: String?
    @Published var showSubscription = false
    @Published var showSettings = false
    @Published var showPromo = false
    @Published var showDevices = false
    @Published var showAbout = false

    private let api = APIService.shared

    var bg: Color { parseColor(theme?.background_color ?? "#FFFFFF") }
    var fg: Color { parseColor(theme?.text_color ?? "#000000") }
    var toggleOnColor: Color { parseColor(theme?.toggle_on_color ?? "#000000") }
    var toggleOffColor: Color { parseColor(theme?.toggle_off_color ?? "#CCCCCC") }

    init() {
        Task {
            await loadInitialData()
        }
    }

    func loadInitialData() async {
        async let t: () = loadTheme()
        async let p: () = loadProfile()
        await t; await p
    }

    func loadTheme() async {
        theme = try? await api.getTheme()
    }

    func loadProfile() async {
        guard api.isLoggedIn else { return }
        profile = try? await api.getProfile()
    }

    func toggleVPN() async {
        if vpnState == .connected {
            vpnState = .disconnecting
            do {
                try await api.disconnect()
                vpnState = .disconnected
            } catch {
                errorMessage = error.localizedDescription
                vpnState = .connected
            }
        } else if vpnState == .disconnected {
            vpnState = .connecting
            do {
                let _ = try await api.registerDevice(name: UIDevice.current.name, type: "ios")
                try await api.connect()
                vpnState = .connected
                await loadProfile()
            } catch {
                errorMessage = error.localizedDescription
                vpnState = .disconnected
            }
        }
    }

    func logout() {
        api.logout()
        profile = nil
        vpnState = .disconnected
    }

    private func parseColor(_ hex: String) -> Color {
        var hexStr = hex.trimmingCharacters(in: .init(charactersIn: "#"))
        if hexStr.count == 6 { hexStr += "FF" }
        guard let value = UInt64(hexStr, radix: 16) else { return .black }
        let r = Double((value >> 24) & 0xFF) / 255
        let g = Double((value >> 16) & 0xFF) / 255
        let b = Double((value >> 8) & 0xFF) / 255
        return Color(red: r, green: g, blue: b)
    }
}
