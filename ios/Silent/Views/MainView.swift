import SwiftUI

enum VpnState { case disconnected, connecting, connected, disconnecting }

struct MainView: View {
    @EnvironmentObject var vm: MainViewModel
    @State private var showMenu = false

    var body: some View {
        ZStack(alignment: .leading) {
            content
            // Side menu overlay
            if showMenu {
                Color.black.opacity(0.3)
                    .ignoresSafeArea()
                    .onTapGesture { withAnimation(.easeInOut(duration: 0.25)) { showMenu = false } }
                SideMenuView(vm: vm, isShowing: $showMenu)
                    .transition(.move(edge: .leading))
            }
        }
        .animation(.easeInOut(duration: 0.25), value: showMenu)
    }

    var content: some View {
        VStack(spacing: 0) {
            // Navigation bar
            HStack {
                Button { withAnimation { showMenu.toggle() } } label: {
                    Image(systemName: "line.horizontal.3")
                        .font(.system(size: 18, weight: .medium))
                        .foregroundColor(vm.fg)
                }
                Spacer()
                Text(vm.theme?.app_name.uppercased() ?? "SILENT")
                    .font(.system(size: 13, weight: .bold))
                    .tracking(4)
                    .foregroundColor(vm.fg)
                Spacer()
                // Balance button space
                Color.clear.frame(width: 44, height: 44)
            }
            .padding(.horizontal, 20)
            .frame(height: 52)
            .background(vm.bg)

            Divider().opacity(0.1)

            Spacer()

            // Status
            Text(statusText)
                .font(.system(size: 12, weight: .medium))
                .tracking(1)
                .foregroundColor(statusColor)

            Spacer().frame(height: 36)

            // Big toggle
            BigToggle(
                isOn: vm.vpnState == .connected,
                isLoading: vm.vpnState == .connecting || vm.vpnState == .disconnecting,
                onColor: vm.toggleOnColor,
                offColor: vm.toggleOffColor,
                bg: vm.bg,
                action: { Task { await vm.toggleVPN() } }
            )

            Spacer()

            // Bottom subscription bar
            if let sub = vm.profile?.subscription, sub.is_active {
                VStack(spacing: 2) {
                    Text("Оплачено")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(.green)
                    if let exp = sub.expires_at {
                        Text("до \(formatDate(exp))")
                            .font(.system(size: 11))
                            .foregroundColor(vm.fg.opacity(0.5))
                    }
                }
                .padding(.bottom, 36)
            } else {
                Button {
                    // Open subscription sheet
                    vm.showSubscription = true
                } label: {
                    Text("Оформить подписку")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(vm.bg)
                        .frame(maxWidth: .infinity)
                        .frame(height: 48)
                        .background(vm.fg)
                        .cornerRadius(14)
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 36)
            }
        }
        .background(vm.bg.ignoresSafeArea())
    }

    var statusText: String {
        switch vm.vpnState {
        case .connected: return "Подключено"
        case .connecting: return "Подключение..."
        case .disconnecting: return "Отключение..."
        case .disconnected: return "Отключено"
        }
    }

    var statusColor: Color {
        vm.vpnState == .connected ? .green : vm.fg.opacity(0.4)
    }

    func formatDate(_ iso: String) -> String {
        let parts = iso.prefix(10).split(separator: "-")
        guard parts.count == 3 else { return iso }
        return "\(parts[2]).\(parts[1]).\(parts[0])"
    }
}

// MARK: - Big Toggle

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
            // Pulse ring
            if isOn {
                Circle()
                    .fill(onColor.opacity(0.12))
                    .frame(width: 140, height: 140)
                    .scaleEffect(isAnimating ? 1.15 : 1.0)
                    .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: isAnimating)
                    .onAppear { isAnimating = true }
                    .onDisappear { isAnimating = false }
            }

            // Track
            Capsule()
                .fill(isOn ? onColor : offColor)
                .frame(width: 130, height: 64)

            // Thumb
            Circle()
                .fill(bg)
                .overlay(
                    Circle().stroke(isOn ? onColor : offColor, lineWidth: 2)
                )
                .overlay(
                    Group {
                        if isLoading {
                            ProgressView().tint(isOn ? onColor : offColor)
                        }
                    }
                )
                .frame(width: 56, height: 56)
                .offset(x: isOn ? 34 : -34)
                .animation(.spring(dampingFraction: 0.7), value: isOn)
        }
        .frame(width: 160, height: 160)
        .contentShape(Rectangle())
        .onTapGesture {
            if !isLoading { action() }
        }
    }
}
