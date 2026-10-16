import SwiftUI
import UIKit

enum VpnState { case disconnected, connecting, connected, disconnecting }

struct RootView: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        Group {
            if vm.loggedIn {
                MainView()
            } else {
                LoginView()
            }
        }
        .onOpenURL { url in
            guard url.scheme == "silentvpn" else { return }
            Task { await vm.onPaymentReturn() }
        }
    }
}

struct MainView: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        ZStack(alignment: .leading) {
            home(p)
            if vm.menuPage != .root {
                MenuPageHost()
                    .background(p.bg.ignoresSafeArea())
                    .zIndex(1)
            }
            if vm.menuOpen && vm.menuPage == .root {
                Color.black.opacity(0.2)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeInOut(duration: 0.2)) { vm.menuOpen = false } }
                drawer(p)
                    .transition(.move(edge: .leading))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: vm.menuOpen)
    }

    private func home(_ p: Palette) -> some View {
        VStack(spacing: 0) {
            HStack {
                Button { withAnimation { vm.menuOpen.toggle() } } label: {
                    Image(systemName: "line.horizontal.3")
                        .font(AppFont.text(18, weight: .medium))
                        .foregroundColor(p.fg)
                        .frame(width: 44, height: 44)
                }
                Spacer()
                Text(displayName)
                    .font(AppFont.text(13, weight: .bold))
                    .tracking(3)
                    .foregroundColor(p.fg)
                Spacer()
                Button(action: vm.toggleAppearance) {
                    Image(systemName: vm.darkMode ? "sun.max" : "moon")
                        .font(AppFont.text(16, weight: .medium))
                        .foregroundColor(p.fg)
                        .frame(width: 44, height: 44)
                }
            }
            .padding(.horizontal, 12)
            .frame(height: 52)

            ZStack {
                if let url = ThemePalette.assetURL(vm.theme?.home_bg_image_url ?? "") {
                    AsyncImage(url: url) { image in
                        image.resizable().scaledToFill().saturation(0).opacity(0.22)
                    } placeholder: { Color.clear }
                }
                VStack(spacing: 0) {
                    Spacer()
                    Text(statusText)
                        .font(AppFont.text(12, weight: .medium))
                        .tracking(1)
                        .foregroundColor(vm.vpnState == .connected ? Color(red: 0.09, green: 0.64, blue: 0.29) : p.fg.opacity(0.4))
                    Spacer().frame(height: 36)
                    BigToggle(
                        isOn: vm.vpnState == .connected,
                        isLoading: vm.vpnState == .connecting || vm.vpnState == .disconnecting,
                        onColor: p.on,
                        offColor: p.off,
                        bg: p.bg,
                        action: { Task { await vm.toggleVPN() } }
                    )
                    if let errorMessage = vm.errorMessage {
                        Text(errorMessage)
                            .font(AppFont.text(12))
                            .foregroundColor(.red)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 24)
                            .padding(.top, 16)
                    }
                    Spacer()
                    if vm.hasAccess {
                        VStack(spacing: 2) {
                            Text("Оплачено")
                                .font(AppFont.text(12, weight: .semibold))
                                .foregroundColor(Color(red: 0.09, green: 0.64, blue: 0.29))
                            if let exp = vm.profile?.subscription.expires_at {
                                Text("до \(formatDate(exp))")
                                    .font(AppFont.text(11))
                                    .foregroundColor(p.fg.opacity(0.5))
                            }
                            Text("Сессии \(vm.profile?.sessionsBadge ?? "0/3")")
                                .font(AppFont.text(11))
                                .foregroundColor(p.fg.opacity(0.4))
                        }
                        .padding(.bottom, 36)
                    } else {
                        Button {
                            vm.menuPage = .subscription
                        } label: {
                            Text("Оформить подписку")
                                .font(AppFont.text(14, weight: .semibold))
                                .foregroundColor(p.bg)
                                .frame(maxWidth: .infinity)
                                .frame(height: 48)
                                .background(p.fg)
                                .cornerRadius(14)
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 36)
                    }
                }
            }
        }
        .background(p.bg.ignoresSafeArea())
    }

    private func drawer(_ p: Palette) -> some View {
        let items: [(MenuPage, String)] = [
            (.subscription, "Подписка"),
            (.exclusions, "Исключения"),
            (.dns, "DNS  ·  \(vm.dnsPreset == "custom" ? "Свой DNS" : "Как на сервере")"),
            (.server, "Выбор сервера  ·  сервер"),
            (.bonuses, vm.theme?.menu_bonuses_label.nilIfEmpty ?? "Бонусы"),
            (.devices, "Сессии (\(vm.profile?.sessionsBadge ?? "0/3"))"),
            (.support, "Поддержка"),
            (.about, "О сервисе"),
        ]
        return VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(vm.profile?.email ?? "—")
                            .font(AppFont.text(12, weight: .semibold))
                            .foregroundColor(p.fg)
                            .lineLimit(1)
                        Text("Аккаунт: \(vm.profile?.display_id ?? "—")")
                            .font(AppFont.text(12))
                            .foregroundColor(p.fg.opacity(0.4))
                    }
                    Spacer()
                    Button { withAnimation { vm.menuOpen = false } } label: {
                        Image(systemName: "xmark")
                            .font(AppFont.text(14, weight: .medium))
                            .foregroundColor(p.fg)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 14)
            }
            Divider().opacity(0.15)
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(items, id: \.0) { page, title in
                        Button {
                            vm.menuPage = page
                            vm.menuOpen = false
                            if page == .bonuses { Task { await vm.loadReferral() } }
                            if page == .subscription { Task { await vm.loadPlans() } }
                            if page == .server { Task { await vm.refreshServers() } }
                        } label: {
                            HStack {
                                Text(title)
                                    .font(AppFont.text(14))
                                    .foregroundColor(p.fg)
                                Spacer()
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 10)
                        }
                    }
                    #if DEBUG
                    if let proxy = vm.theme?.telegram_proxy_url.nilIfEmpty {
                        Button {
                            vm.menuOpen = false
                            let deep: String
                            if proxy.lowercased().hasPrefix("tg://") {
                                deep = proxy
                            } else if proxy.lowercased().contains("t.me/proxy?") {
                                deep = "tg://proxy?" + proxy.components(separatedBy: "t.me/proxy?").last!
                            } else {
                                deep = proxy
                            }
                            if let url = URL(string: deep) { UIApplication.shared.open(url) }
                        } label: {
                            HStack {
                                Text(vm.theme?.telegram_proxy_menu_label.nilIfEmpty ?? "Ускорить Telegram")
                                    .font(AppFont.text(14))
                                    .foregroundColor(p.fg)
                                Spacer()
                            }
                            .padding(.horizontal, 12)
                            .padding(.vertical, 10)
                        }
                    }
                    #endif
                    Button(action: vm.logout) {
                        Text("Выйти")
                            .font(AppFont.text(14, weight: .medium))
                            .foregroundColor(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 16)
                    }
                }
            }
        }
        .frame(width: 208)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(p.bg)
    }

    private var displayName: String {
        let raw = vm.theme?.app_name.nilIfEmpty ?? "Silent VPN"
        return (raw.caseInsensitiveCompare("Silent") == .orderedSame ? "Silent VPN" : raw).uppercased()
    }

    private var statusText: String {
        switch vm.vpnState {
        case .connected: return "Подключено"
        case .connecting: return "Подключение..."
        case .disconnecting: return "Отключение..."
        case .disconnected: return "Отключено"
        }
    }

    private func formatDate(_ iso: String) -> String {
        let parts = iso.prefix(10).split(separator: "-")
        guard parts.count == 3 else { return iso }
        return "\(parts[2]).\(parts[1]).\(parts[0])"
    }
}

struct BigToggle: View {
    let isOn: Bool
    let isLoading: Bool
    let onColor: Color
    let offColor: Color
    let bg: Color
    let action: () -> Void
    @State private var isAnimating = false

    var body: some View {
        ZStack {
            if isOn {
                Circle()
                    .fill(onColor.opacity(0.12))
                    .frame(width: 140, height: 140)
                    .scaleEffect(isAnimating ? 1.15 : 1.0)
                    .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: isAnimating)
                    .onAppear { isAnimating = true }
            }
            Capsule()
                .fill(isOn ? onColor : offColor)
                .frame(width: 130, height: 64)
            Circle()
                .fill(bg)
                .overlay(Circle().stroke(isOn ? onColor : offColor, lineWidth: 2))
                .overlay { if isLoading { ProgressView().tint(isOn ? onColor : offColor) } }
                .frame(width: 56, height: 56)
                .offset(x: isOn ? 34 : -34)
                .animation(.spring(response: 0.35, dampingFraction: 0.7), value: isOn)
        }
        .frame(width: 160, height: 160)
        .contentShape(Rectangle())
        .onTapGesture { if !isLoading { action() } }
    }
}
