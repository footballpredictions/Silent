import SwiftUI

@main
struct SilentApp: App {
    @StateObject private var vm = MainViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(vm)
                .preferredColorScheme(vm.darkMode ? .dark : .light)
        }
    }
}
