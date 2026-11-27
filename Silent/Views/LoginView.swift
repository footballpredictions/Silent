import SwiftUI
import UIKit

struct LoginView: View {
    @EnvironmentObject var vm: MainViewModel
    @State private var tab = "login"
    @State private var email = LocalStore.rememberMe ? LocalStore.rememberedEmail : ""
    @State private var password = LocalStore.rememberMe ? LocalStore.rememberedPassword : ""
    @State private var code = ""
    @AppStorage("remember_me") private var remember = false
    @State private var showPassword = false
    @State private var forgot = false
    @State private var closing = false
    @State private var closeFailed = false

    var body: some View {
        let p = vm.palette
        VStack(spacing: 0) {
            HStack {
                Spacer()
                ThemeModeButton(dark: vm.darkMode, ink: p.fg, action: vm.toggleAppearance)
                ConnectionLogButton(palette: p)
            }
            .padding(.horizontal, 16)

            GeometryReader { geometry in
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        SilentBrandHeader(title: displayName, color: p.fg)

                        if vm.bootstrapExpired {
                            expiredPanel(p: p)
                        } else {
                            authContent(p: p)
                        }
                    }
                    .frame(maxWidth: 440)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 24)
                    .frame(maxWidth: .infinity, minHeight: geometry.size.height, alignment: .center)
                }
            }
        }
        .background(p.bg.ignoresSafeArea())
        .task(id: vm.bootstrapDeadline) { [deadline = vm.bootstrapDeadline] in
            guard let deadline else { return }
            do { try await Task.sleep(for: .seconds(max(0, deadline.timeIntervalSinceNow))) }
            catch { return }
            vm.expireBootstrap(at: deadline)
        }
        .alert("Закройте приложение", isPresented: $closeFailed) {
            Button("Понятно", role: .cancel) {}
        } message: {
            Text("Откройте список недавних приложений и смахните Silent VPN вверх.")
        }
    }

    @ViewBuilder
    private func authContent(p: Palette) -> some View {
        let theme = vm.theme
        if vm.bootstrapReconnecting {
            Text("Временный интернет · восстановление связи…")
                .font(AppFont.text(12, weight: .medium))
                .foregroundStyle(p.success)
                .shadow(color: p.successGlow, radius: 4)
        } else if vm.bootstrapStarting {
            Text(vm.registrationEmail == nil ? "Подключение временного VPN…" : "Настраиваем интернет для почты…")
                .font(.footnote)
                .foregroundColor(p.fg.opacity(0.7))
        } else if let deadline = vm.bootstrapDeadline {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let seconds = max(0, Int(ceil(deadline.timeIntervalSince(context.date))))
                let title = vm.bootstrapMailReady ? "Интернет для почты" : "Временный интернет"
                Label("\(title) · \(seconds / 60):\(String(format: "%02d", seconds % 60))", systemImage: "timer")
                    .font(.footnote.weight(.medium).monospacedDigit())
                    .foregroundStyle(p.success)
                    .shadow(color: p.successGlow, radius: 4)
            }
        }

        if forgot {
            Text(theme?.login_forgot_title ?? "Восстановление пароля")
                .font(AppFont.text(16, weight: .semibold))
                .foregroundColor(p.fg)
            Text(theme?.login_forgot_instruction ?? "")
                .font(AppFont.text(12))
                .foregroundColor(p.fg.opacity(0.55))
            field("Email", text: $email, p: p)
            if vm.forgotSent {
                Text("Если email зарегистрирован, письмо отправлено.")
                    .font(AppFont.text(12))
                    .foregroundColor(p.fg.opacity(0.7))
            }
            primaryButton("Отправить", p: p) {
                Task { await vm.forgot(email: email) }
            }
            Button("Назад ко входу") { forgot = false; vm.forgotSent = false }
                .font(AppFont.text(13, weight: .medium))
                .foregroundColor(p.link)
        } else {
            HStack(spacing: 8) {
                chip("Войти", on: tab == "login", p: p) { returnToLogin() }
                chip("Регистрация", on: tab == "register", p: p) {
                    tab = "register"
                    vm.dismissRegistrationConfirmation()
                }
            }
            .disabled(vm.authLoading || vm.bootstrapStarting || vm.verificationResending)
            if let address = vm.registrationEmail {
                registrationConfirmation(address, p: p)
            } else {
                credentialsForm(p: p)
            }
        }
        if let authError = vm.authError {
            Text(authError).font(.footnote).foregroundColor(.red)
        }
        if !vm.bootstrapStarting && (vm.bootstrapFailed || (vm.registrationEmail != nil && !vm.bootstrapMailReady)) {
            Button(vm.registrationEmail == nil ? "Повторить временный VPN" : "Включить интернет для почты") {
                Task { await vm.retryBootstrap() }
            }
                .font(.subheadline.weight(.medium))
                .foregroundStyle(p.link)
                .frame(minHeight: 44, alignment: .leading)
                .disabled(vm.authLoading || vm.verificationResending)
        }
    }

    private func expiredPanel(p: Palette) -> some View {
        let accent = ThemePalette.color("EF4444")
        let card = RoundedRectangle(cornerRadius: 16)
        return VStack(spacing: 0) {
            Image(systemName: "clock")
                .font(AppFont.text(22))
                .foregroundStyle(accent)
                .frame(width: 44, height: 44)
                .background(accent.opacity(0.10), in: Circle())
                .accessibilityHidden(true)
            Text("Время вышло")
                .font(AppFont.text(14, weight: .semibold))
                .foregroundStyle(p.fg)
                .accessibilityAddTraits(.isHeader)
                .padding(.top, 14)
            Text("Временный интернет на 2 минуты закончился.\nЗакройте приложение и откройте снова.")
                .font(AppFont.text(12))
                .foregroundStyle(p.fg.opacity(0.65))
                .multilineTextAlignment(.center)
                .padding(.top, 6)
            Button(action: closeExpiredLogin) {
                Text("Закрыть приложение")
                    .font(AppFont.text(14, weight: .semibold))
                    .foregroundStyle(p.bg)
                    .frame(maxWidth: .infinity, minHeight: 48)
                    .background(p.fg, in: RoundedRectangle(cornerRadius: 12))
            }
            .buttonStyle(.plain)
            .disabled(closing)
            .padding(.top, 18)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 22)
        .frame(maxWidth: .infinity)
        .background(accent.opacity(0.05), in: card)
        .overlay(card.strokeBorder(accent.opacity(0.18), lineWidth: 1).allowsHitTesting(false))
    }

    private func closeExpiredLogin() {
        guard !closing else { return }
        closing = true
        Task { @MainActor in
            let app = UIApplication.shared
            let scenes = app.connectedScenes.compactMap { $0 as? UIWindowScene }
                .filter { $0.activationState == .foregroundActive }
            let scene = scenes.first(where: { $0.windows.contains(where: \.isKeyWindow) }) ?? scenes.first
            guard await vm.prepareToCloseExpiredLogin(), let scene else {
                closing = false
                closeFailed = true
                return
            }
            app.requestSceneSessionDestruction(scene.session, options: nil) { _ in
                Task { @MainActor in
                    closing = false
                    closeFailed = true
                }
            }
        }
    }

    private var displayName: String {
        let raw = vm.theme?.app_name.nilIfEmpty ?? "Silent VPN"
        return (raw.caseInsensitiveCompare("Silent") == .orderedSame ? "Silent VPN" : raw).uppercased()
    }

    private func returnToLogin() {
        tab = "login"
        vm.dismissRegistrationConfirmation()
    }

    private func registrationConfirmation(_ address: String, p: Palette) -> some View {
        VStack(spacing: 6) {
            Text("Подтвердите email")
                .font(.headline)
                .foregroundStyle(p.fg)
                .accessibilityAddTraits(.isHeader)
            Text("Адрес для подтверждения — \(address)")
                .font(.subheadline)
                .foregroundStyle(p.fg.opacity(0.72))
            Text("Откройте «Почту» на iPhone и нажмите ссылку из письма.")
                .font(.footnote)
                .foregroundStyle(p.fg.opacity(0.65))
            if let notice = vm.verificationNotice {
                Text(notice)
                    .font(.footnote)
                    .foregroundStyle(p.success)
                    .shadow(color: p.successGlow, radius: 4)
            }
            Button {
                Task { await vm.resendVerification(password: password) }
            } label: {
                if vm.verificationResending {
                    ProgressView().tint(p.fg)
                } else {
                    Text("Отправить письмо ещё раз")
                }
            }
            .font(.subheadline.weight(.medium))
            .foregroundStyle(p.link)
            .frame(minHeight: 44)
            .disabled(vm.authLoading || vm.bootstrapStarting || vm.verificationResending || password.isEmpty)
            Button("Войти", action: returnToLogin)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(p.fg)
                .frame(minHeight: 44)
                .disabled(vm.authLoading || vm.bootstrapStarting || vm.verificationResending)
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .padding(.top, 24)
    }

    @ViewBuilder
    private func credentialsForm(p: Palette) -> some View {
        let theme = vm.theme
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        field("Email", text: $email, p: p)
            .keyboardType(.emailAddress)
            .textContentType(.emailAddress)
        passwordField(p: p)
        if tab == "register" {
            field(theme?.register_referral_or_promo_label ?? "Промокод или реферальный код", text: $code, p: p)
            Text(theme?.register_referral_or_promo_hint ?? "Необязательно")
                .font(AppFont.text(11))
                .foregroundColor(p.fg.opacity(0.65))
        } else {
            Toggle(isOn: $remember) {
                Text(theme?.login_remember_me_label ?? "Запомнить меня")
                    .font(AppFont.text(13))
                    .foregroundColor(p.fg)
            }
            .tint(p.switchOn)
            .onChange(of: remember) { enabled in
                if !enabled {
                    LocalStore.rememberedEmail = ""
                    LocalStore.rememberedPassword = ""
                }
            }
            Button(theme?.login_forgot_password_label ?? "Забыли пароль?") { forgot = true }
                .font(AppFont.text(13, weight: .medium))
                .foregroundColor(p.link)
        }
        primaryButton(tab == "login" ? "Войти" : "Зарегистрироваться", p: p) {
            Task {
                if tab == "login" {
                    await vm.login(email: address, password: password, remember: remember)
                } else {
                    await vm.register(email: address, password: password, code: code, remember: remember)
                }
            }
        }
        .disabled(address.isEmpty || password.isEmpty || (tab == "register" && password.count < 8))
    }

    private func chip(_ title: String, on: Bool, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(AppFont.text(13, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
                .foregroundColor(on ? p.bg : p.fg)
                .background(on ? p.fg : p.fg.opacity(0.06))
                .cornerRadius(12)
        }
    }

    private func field(_ title: String, text: Binding<String>, p: Palette) -> some View {
        TextField(title, text: text)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .font(AppFont.text(14))
            .padding(14)
            .background(p.fg.opacity(0.05))
            .cornerRadius(12)
            .foregroundColor(p.fg)
    }

    private func passwordField(p: Palette) -> some View {
        HStack {
            Group {
                if showPassword {
                    TextField("Пароль", text: $password)
                } else {
                    SecureField("Пароль", text: $password)
                }
            }
            .textInputAutocapitalization(.never)
            .font(AppFont.text(14))
            Button { showPassword.toggle() } label: {
                Image(systemName: showPassword ? "eye.slash" : "eye")
                    .foregroundColor(p.fg.opacity(0.45))
            }
        }
        .padding(14)
        .background(p.fg.opacity(0.05))
        .cornerRadius(12)
        .foregroundColor(p.fg)
    }

    private func primaryButton(_ title: String, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if vm.authLoading { ProgressView().tint(p.bg) }
                Text(vm.authLoading ? vm.authLoadingTitle : title)
            }
                .font(AppFont.text(14, weight: .semibold))
                .foregroundColor(p.bg)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .background(p.fg)
                .cornerRadius(14)
        }
        .disabled(vm.authLoading || vm.bootstrapStarting)
    }
}
