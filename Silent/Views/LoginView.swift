import SwiftUI

struct LoginView: View {
    @EnvironmentObject var vm: MainViewModel
    @State private var tab = "login"
    @State private var email = LocalStore.rememberedEmail
    @State private var password = LocalStore.rememberedPassword
    @State private var code = ""
    @State private var remember = LocalStore.rememberMe
    @State private var showPassword = false
    @State private var forgot = false

    var body: some View {
        let p = vm.palette
        let theme = vm.theme
        VStack(spacing: 0) {
            HStack {
                Spacer()
                Button(action: vm.toggleAppearance) {
                    Image(systemName: vm.darkMode ? "sun.max" : "moon")
                        .font(AppFont.text(16, weight: .medium))
                        .foregroundColor(p.fg)
                        .frame(width: 36, height: 36)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(displayName)
                        .font(AppFont.text(13, weight: .bold))
                        .tracking(3)
                        .foregroundColor(p.fg)
                        .frame(maxWidth: .infinity)
                        .padding(.top, 12)

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
                        primaryButton(vm.authLoading ? "…" : "Отправить", p: p) {
                            Task { await vm.forgot(email: email) }
                        }
                        Button("Назад ко входу") { forgot = false; vm.forgotSent = false }
                            .font(AppFont.text(13, weight: .medium))
                            .foregroundColor(p.link)
                    } else {
                        HStack(spacing: 8) {
                            chip("Войти", on: tab == "login", p: p) { tab = "login" }
                            chip("Регистрация", on: tab == "register", p: p) { tab = "register" }
                        }
                        if vm.regNeedMail {
                            Text("Подтвердите email — мы отправили письмо. После этого войдите.")
                                .font(AppFont.text(12))
                                .foregroundColor(p.fg.opacity(0.7))
                        }
                        field("Email", text: $email, p: p)
                        passwordField(p: p)
                        if tab == "register" {
                            field(theme?.register_referral_or_promo_label ?? "Промокод или реферальный код", text: $code, p: p)
                            Text(theme?.register_referral_or_promo_hint ?? "")
                                .font(AppFont.text(11))
                                .foregroundColor(p.fg.opacity(0.45))
                        } else {
                            Toggle(isOn: $remember) {
                                Text(theme?.login_remember_me_label ?? "Запомнить меня")
                                    .font(AppFont.text(13))
                                    .foregroundColor(p.fg)
                            }
                            .tint(p.fg)
                            Button(theme?.login_forgot_password_label ?? "Забыли пароль?") { forgot = true }
                                .font(AppFont.text(13, weight: .medium))
                                .foregroundColor(p.link)
                        }
                        if let authError = vm.authError {
                            Text(authError).font(AppFont.text(12)).foregroundColor(.red)
                        }
                        primaryButton(vm.authLoading ? "…" : (tab == "login" ? "Войти" : "Создать аккаунт"), p: p) {
                            Task {
                                if tab == "login" {
                                    await vm.login(email: email, password: password, remember: remember)
                                } else {
                                    await vm.register(email: email, password: password, code: code, remember: remember)
                                }
                            }
                        }
                        .disabled(vm.authLoading || email.isEmpty || password.count < 8 && tab == "register" || password.isEmpty)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 32)
            }
        }
        .background(p.bg.ignoresSafeArea())
    }

    private var displayName: String {
        let raw = vm.theme?.app_name.nilIfEmpty ?? "Silent VPN"
        return (raw.caseInsensitiveCompare("Silent") == .orderedSame ? "Silent VPN" : raw).uppercased()
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
            Text(title)
                .font(AppFont.text(14, weight: .semibold))
                .foregroundColor(p.bg)
                .frame(maxWidth: .infinity)
                .frame(height: 48)
                .background(p.fg)
                .cornerRadius(14)
        }
    }
}
