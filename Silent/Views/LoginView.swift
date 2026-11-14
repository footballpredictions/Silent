import SwiftUI

struct LoginView: View {
    @EnvironmentObject var vm: MainViewModel
    @State private var tab = "login"
    @State private var email = LocalStore.rememberMe ? LocalStore.rememberedEmail : ""
    @State private var password = LocalStore.rememberMe ? LocalStore.rememberedPassword : ""
    @State private var code = ""
    @AppStorage("remember_me") private var remember = false
    @State private var showPassword = false
    @State private var forgot = false

    var body: some View {
        let p = vm.palette
        let theme = vm.theme
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

                        if vm.bootstrapReconnecting {
                            Text("Временный интернет · восстановление связи…")
                                .font(AppFont.text(12, weight: .medium))
                                .foregroundStyle(p.success)
                                .shadow(color: p.successGlow, radius: 4)
                        } else if let deadline = vm.bootstrapDeadline {
                            TimelineView(.periodic(from: .now, by: 1)) { context in
                                let seconds = max(0, Int(ceil(deadline.timeIntervalSince(context.date))))
                                Label("Временный интернет · \(seconds / 60):\(String(format: "%02d", seconds % 60))", systemImage: "timer")
                                    .font(.footnote.weight(.medium).monospacedDigit())
                                    .foregroundStyle(p.success)
                                    .shadow(color: p.successGlow, radius: 4)
                            }
                        } else if vm.bootstrapStarting {
                            Text("Подключение временного VPN…")
                                .font(.footnote)
                                .foregroundColor(p.fg.opacity(0.7))
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
                                    vm.authError = nil
                                }
                            }
                            .disabled(vm.authLoading)
                            if let address = vm.registrationEmail {
                                registrationConfirmation(address, p: p)
                            } else {
                                credentialsForm(p: p)
                            }
                        }
                        if let authError = vm.authError {
                            Text(authError).font(.footnote).foregroundColor(.red)
                        }
                        if vm.bootstrapFailed && !vm.bootstrapStarting {
                            Button("Повторить временный VPN") { Task { await vm.retryBootstrap() } }
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(p.link)
                                .frame(minHeight: 44, alignment: .leading)
                                .disabled(vm.authLoading)
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
            Text("Ссылка отправлена на \(address)")
                .font(.subheadline)
                .foregroundStyle(p.fg.opacity(0.72))
            Text("Откройте ссылку из письма в браузере или приложении почты.")
                .font(.footnote)
                .foregroundStyle(p.fg.opacity(0.65))
            Button("Войти", action: returnToLogin)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(p.fg)
                .frame(minHeight: 44)
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
