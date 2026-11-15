import SwiftUI
import UIKit

@main
struct SilentApp: App {
    @UIApplicationDelegateAdaptor(SilentAppDelegate.self) private var appDelegate
    @StateObject private var vm = MainViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(vm)
                .preferredColorScheme(vm.darkMode ? .dark : .light)
        }
    }
}

@MainActor
final class SilentAppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, didDiscardSceneSessions sceneSessions: Set<UISceneSession>) {
        VpnManager.shared.sceneSessionsDiscarded(Set(sceneSessions.map(\.persistentIdentifier)))
    }
}
