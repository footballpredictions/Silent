import SwiftUI
import UIKit

enum VpnState { case disconnected, connecting, connected, reconnecting, disconnecting }

struct RootView: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        Group {
            if let stage = vm.launchStage {
                LaunchSplash(stage: stage, palette: vm.palette)
            } else if vm.loggedIn {
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
        GeometryReader { geometry in
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
                        .frame(width: min(360, geometry.size.width * 0.79))
                        .transition(.move(edge: .leading))
                }
            }
            .animation(.easeInOut(duration: 0.2), value: vm.menuOpen)
        }
    }

    private func home(_ p: Palette) -> some View {
        VStack(spacing: 0) {
            ZStack {
                Text(displayName)
                    .font(AppFont.text(13, weight: .bold))
                    .tracking(3)
                    .foregroundColor(p.fg)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                    .padding(.horizontal, 104)

                HStack(spacing: 4) {
                    Button { withAnimation { vm.menuOpen.toggle() } } label: {
                        Image(systemName: "line.horizontal.3")
                            .font(AppFont.text(18, weight: .medium))
                            .foregroundColor(p.fg)
                            .frame(width: 44, height: 44)
                    }
                    .accessibilityLabel("Меню")
                    Spacer()
                    ThemeModeButton(dark: vm.darkMode, ink: p.fg, action: vm.toggleAppearance)
                    ConnectionLogButton(palette: p)
                }
                .padding(.horizontal, 8)
            }
            .frame(height: 52)
            Divider().overlay(p.fg.opacity(0.14))

            VStack(spacing: 12) {
                Text(statusText)
                    .font(AppFont.text(12, weight: .medium))
                    .tracking(1)
                    .foregroundColor(vm.vpnState == .connected ? p.success : p.fg.opacity(0.65))
                    .shadow(color: vm.vpnState == .connected ? p.successGlow : .clear, radius: 4)
                BigToggle(
                    isOn: vm.vpnState == .connected || vm.vpnState == .connecting || vm.vpnState == .reconnecting,
                    isLoading: vm.vpnState != .connected && vm.vpnState != .disconnected,
                    isDisabled: !vm.canLogout || vm.vpnState == .connecting || vm.vpnState == .disconnecting,
                    onColor: p.on, offColor: p.off, bg: p.bg,
                    progressColor: p.dark ? Color(white: 0.65) : Color(white: 0.34),
                    status: statusText,
                    action: { Task { await vm.toggleVPN() } }
                )
                if let errorMessage = vm.errorMessage {
                    Text(errorMessage)
                        .font(.footnote)
                        .foregroundColor(.red)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)
                }
            }
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider().overlay(p.fg.opacity(0.14))
            accessFooter(p)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
        }
        .background(p.bg.ignoresSafeArea())
    }

    @ViewBuilder
    private func accessFooter(_ p: Palette) -> some View {
        if let profile = vm.profile {
            let subscription = profile.subscription
            if profile.is_admin || (subscription.is_active && subscription.plan_type == "unlimited") {
                accessStatus("Бессрочно", detail: "Полный доступ", color: p.success, glow: p.successGlow, palette: p)
            } else if subscription.is_active && subscription.plan_type == "test" {
                accessStatus("Тестовый режим", detail: "Безлимит", color: .purple, palette: p)
            } else if subscription.is_active && subscription.plan_type == "trial" {
                accessStatus("Пробный период", detail: "Осталось \(subscription.days_left) дн.", color: .blue, palette: p)
            } else if subscription.is_active {
                let detail = subscription.expires_at.map { "до \(formatDate($0))" }
                    ?? "Осталось \(subscription.days_left) дн."
                accessStatus("Оплачено", detail: detail, color: p.success, glow: p.successGlow, palette: p)
            } else {
                Button { vm.menuPage = .subscription } label: {
                    Text("Оформить подписку")
                        .font(.footnote.weight(.semibold))
                        .foregroundColor(p.bg)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background(p.fg, in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
            }
        } else {
            ProgressView().tint(p.fg).accessibilityLabel("Загрузка аккаунта")
        }
    }

    private func accessStatus(_ title: String, detail: String, color: Color, glow: Color = .clear, palette p: Palette) -> some View {
        VStack(spacing: 3) {
            Text(title).font(.footnote.weight(.semibold)).foregroundColor(color).shadow(color: glow, radius: 4)
            Text(detail).font(.footnote).foregroundColor(p.fg.opacity(0.65))
        }
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
                            .font(.subheadline.weight(.semibold))
                            .foregroundColor(p.fg)
                            .lineLimit(1)
                        Text("Аккаунт: \(vm.profile?.display_id ?? "—")")
                            .font(.footnote)
                            .foregroundColor(p.fg.opacity(0.65))
                        if let id = vm.sessionDeviceId {
                            Text("Сессия: \(id.prefix(8).uppercased())")
                                .font(.footnote.monospacedDigit())
                                .foregroundColor(p.fg.opacity(0.65))
                        }
                    }
                    Spacer()
                    Button { withAnimation { vm.menuOpen = false } } label: {
                        Image(systemName: "xmark")
                            .font(.body.weight(.medium))
                            .foregroundColor(p.fg)
                    }
                    .frame(width: 44, height: 44)
                    .accessibilityLabel("Закрыть меню")
                }
                .padding(.horizontal, 18)
                .padding(.vertical, 14)
            }
            Divider().overlay(p.fg.opacity(0.14))
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(items, id: \.0) { page, title in
                        Button {
                            vm.menuPage = page
                            vm.menuOpen = false
                            if page == .bonuses { Task { await vm.loadReferral() } }
                            if page == .subscription { Task { await vm.loadPlans() } }
                        } label: {
                            HStack {
                                Text(title)
                                    .font(.body)
                                    .foregroundColor(p.fg)
                                Spacer()
                            }
                            .padding(.horizontal, 18)
                            .frame(minHeight: 48)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
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
                                    .font(.body)
                                    .foregroundColor(p.fg)
                                Spacer()
                            }
                            .padding(.horizontal, 18)
                            .frame(minHeight: 48)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                    #endif
                    Button(action: vm.logout) {
                        Text("Выйти")
                            .font(.body.weight(.medium))
                            .foregroundColor(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 18)
                            .padding(.vertical, 16)
                    }
                    .disabled(!vm.canLogout)
                }
            }
        }
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
        case .reconnecting: return "Восстановление связи…"
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
    let isDisabled: Bool
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
            .frame(width: 154, height: 92)
            .contentShape(Rectangle())
        }
        .buttonStyle(VpnToggleButtonStyle(reduceMotion: reduceMotion))
        .disabled(isDisabled)
        .accessibilityLabel(isOn ? "Отключить VPN" : "Подключить VPN")
        .accessibilityValue(status)
    }

    private func track(at time: TimeInterval) -> some View {
        let pulse = reduceMotion ? 1.0 : 1 + 0.06 * (1 - cos(time * 2 * .pi / 3))
        let thumb = reduceMotion ? 1.0 : 1 + 0.05 * (1 - cos(time * 2 * .pi / 1.04))
        let rotation = reduceMotion ? 0 : time.truncatingRemainder(dividingBy: 2.2) / 2.2 * 360
        let color = isOn ? onColor : offColor
        return ZStack {
            if isOn && !isLoading {
                Capsule()
                    .fill(onColor.opacity(0.20))
                    .frame(width: 132, height: 66)
                    .scaleEffect(pulse)
            }
            Capsule().fill(color).frame(width: 132, height: 66)
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
                .frame(width: 52, height: 52)
                .scaleEffect(isLoading ? thumb : 1)
                .offset(x: isOn ? 35 : -35)
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
