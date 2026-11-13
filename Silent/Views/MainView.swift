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
    @State private var showConnectionLog = false

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
        .sheet(isPresented: $showConnectionLog) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if vm.connectionLog.isEmpty { Text("Подключений в этой сессии ещё не было.") }
                        ForEach(Array(vm.connectionLog.enumerated()), id: \.offset) { entry in
                            Text(entry.element).font(.footnote.monospacedDigit())
                        }
                        if let error = vm.errorMessage { Text(error).foregroundStyle(.red) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
                }
                .navigationTitle("Журнал подключения")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Готово") { showConnectionLog = false } } }
            }
        }
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
                Button { showConnectionLog = true } label: {
                    Image(systemName: "list.bullet.rectangle")
                        .font(AppFont.text(16, weight: .medium))
                        .foregroundColor(p.fg)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("Журнал подключения")
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
                    Spacer().frame(height: 24)
                    BigToggle(
                        isOn: vm.vpnState == .connected,
                        isLoading: vm.vpnState == .connecting || vm.vpnState == .disconnecting,
                        onColor: p.on,
                        offColor: p.off,
                        bg: p.bg,
                        progressColor: p.link,
                        status: statusText,
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
    let progressColor: Color
    let status: String
    let action: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Button(action: action) {
            TimelineView(.animation(minimumInterval: 1.0 / 30, paused: reduceMotion || scenePhase != .active || (!isOn && !isLoading))) { context in
                track(at: context.date.timeIntervalSinceReferenceDate)
            }
            .frame(width: 144, height: 86)
            .contentShape(Rectangle())
        }
        .buttonStyle(VpnToggleButtonStyle(reduceMotion: reduceMotion))
        .disabled(isLoading)
        .accessibilityLabel(isOn ? "Отключить VPN" : "Подключить VPN")
        .accessibilityValue(status)
    }

    private func track(at time: TimeInterval) -> some View {
        let pulse = reduceMotion ? 1.0 : 1 + 0.06 * (1 - cos(time * 2 * .pi / 3))
        let thumb = reduceMotion ? 1.0 : 1 + 0.05 * (1 - cos(time * 2 * .pi / 1.04))
        let rotation = reduceMotion ? 0 : time.truncatingRemainder(dividingBy: 2.2) / 2.2 * 360
        let color = isOn ? onColor : offColor
        return ZStack {
            if isOn {
                Capsule()
                    .fill(onColor.opacity(0.20))
                    .frame(width: 120, height: 60)
                    .scaleEffect(pulse)
            }
            Capsule().fill(color).frame(width: 120, height: 60)
            Circle()
                .fill(bg)
                .overlay {
                    if isLoading {
                        Circle().strokeBorder(
                            AngularGradient(colors: [.clear, .clear, progressColor.opacity(0.35), progressColor, .clear], center: .center),
                            lineWidth: 4
                        )
                        .rotationEffect(.degrees(rotation))
                    } else {
                        Circle().strokeBorder(color, lineWidth: 2)
                    }
                }
                .frame(width: 48, height: 48)
                .scaleEffect(isLoading ? thumb : 1)
                .offset(x: isOn ? 32 : -32)
                .animation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.7), value: isOn)
        }
    }
}

private struct VpnToggleButtonStyle: ButtonStyle {
    let reduceMotion: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.95 : 1)
            .animation(reduceMotion ? nil : .spring(response: 0.22, dampingFraction: 0.65), value: configuration.isPressed)
    }
}
