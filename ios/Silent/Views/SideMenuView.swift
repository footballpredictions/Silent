import SwiftUI

struct SideMenuView: View {
    @ObservedObject var vm: MainViewModel
    @Binding var isShowing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            ZStack(alignment: .topTrailing) {
                VStack(alignment: .leading, spacing: 4) {
                    Spacer().frame(height: 52)
                    Text(vm.profile?.email ?? "—")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(vm.bg)
                        .lineLimit(1)
                    Text("ID: \(vm.profile?.display_id ?? "—")")
                        .font(.system(size: 12))
                        .foregroundColor(vm.bg.opacity(0.6))
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(vm.fg)

                Button { withAnimation { isShowing = false } } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(vm.bg)
                        .padding(12)
                }
            }

            ScrollView {
                VStack(spacing: 0) {
                    menuItem("Подписка", badge: vm.profile?.subscription.is_active == true ? "Активна" : "Нет") {
                        isShowing = false; vm.showSubscription = true
                    }
                    menuItem("Настройки") {
                        isShowing = false; vm.showSettings = true
                    }
                    menuItem("Промокод") {
                        isShowing = false; vm.showPromo = true
                    }
                    menuItem("Устройства", badge: "\(vm.profile?.devices_count ?? 0)/\(vm.profile?.max_devices ?? 3)") {
                        isShowing = false; vm.showDevices = true
                    }
                    menuItem("Поддержка") {
                        isShowing = false
                        if let url = URL(string: vm.theme?.support_url ?? "") { UIApplication.shared.open(url) }
                    }
                    menuItem("О сервисе") {
                        isShowing = false; vm.showAbout = true
                    }
                }
            }

            Spacer()

            Button {
                isShowing = false
                vm.logout()
            } label: {
                Text("Выйти")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(.red)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 16)
            }
            Spacer().frame(height: 32)
        }
        .frame(width: 280)
        .background(vm.bg)
        .shadow(color: .black.opacity(0.2), radius: 20, x: 10, y: 0)
    }

    @ViewBuilder
    func menuItem(_ title: String, badge: String? = nil, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(title)
                    .font(.system(size: 14))
                    .foregroundColor(vm.fg)
                Spacer()
                if let badge {
                    Text(badge)
                        .font(.system(size: 12))
                        .foregroundColor(vm.fg.opacity(0.4))
                }
                Image(systemName: "chevron.right")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundColor(vm.fg.opacity(0.3))
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
        }
        Divider().opacity(0.06).padding(.leading, 20)
    }
}
