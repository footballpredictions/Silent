import SwiftUI
import UIKit

struct MenuPageHost: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 0) {
            Button { vm.menuPage = .root } label: {
                Text("← Назад")
                    .font(AppFont.text(12))
                    .foregroundColor(p.fg.opacity(0.4))
                    .padding(.bottom, 12)
            }
            .padding(.horizontal, 16)
            .padding(.top, 16)
            Group {
                switch vm.menuPage {
                case .subscription: SubscriptionPage()
                case .exclusions: ExclusionsPage()
                case .dns: DnsPage()
                case .server: ServerPage()
                case .bonuses: BonusesPage()
                case .devices: DevicesPage()
                case .support: SupportPage()
                case .about: AboutPage()
                case .root: EmptyView()
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(p.bg)
    }
}

private struct SubscriptionPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let theme = vm.theme
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                switch vm.payment {
                case .waiting:
                    Text(theme?.payment_waiting_title ?? "").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                    Text(theme?.payment_waiting_text ?? "").font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.55))
                    Button(theme?.payment_cancel_button_text ?? "Отмена") { vm.resetPayment() }
                        .font(AppFont.text(13)).foregroundColor(p.link)
                case .success:
                    Text(theme?.payment_success_title ?? "").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                    Text(theme?.payment_success_text ?? "").font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.55))
                    Button("Закрыть") { vm.resetPayment() }.font(AppFont.text(13)).foregroundColor(p.link)
                case .failed:
                    Text(theme?.payment_failed_title ?? "").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                    Text(vm.paymentError ?? theme?.payment_failed_text ?? "").font(AppFont.text(12)).foregroundColor(.red)
                    Button(theme?.payment_retry_button_text ?? "Попробовать снова") { vm.resetPayment() }
                        .font(AppFont.text(13)).foregroundColor(p.link)
                case .timeout:
                    Text(theme?.payment_timeout_title ?? "").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                    Text(theme?.payment_timeout_text ?? "").font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.55))
                    Button(theme?.payment_retry_button_text ?? "Попробовать снова") { vm.resetPayment() }
                        .font(AppFont.text(13)).foregroundColor(p.link)
                case .idle:
                    Text("Подписка и оплата обновляются автоматически при включённом VPN.")
                        .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.45))
                    if (vm.profile?.subscription.is_active == true || vm.profile?.is_admin == true) && !vm.showSubscriptionShop {
                        Text("Подписка активна").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                        Text(activeText).font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.5))
                        if vm.profile?.is_admin != true && !["unlimited", "test"].contains(vm.profile?.subscription.plan_type ?? "") {
                            Button(theme?.subscription_pay_early_label ?? "Оплатить заранее") {
                                vm.tier = vm.profile?.max_devices == 5 ? 5 : 3
                                vm.showSubscriptionShop = true
                            }.font(AppFont.text(14, weight: .semibold))
                                .foregroundColor(p.bg).frame(maxWidth: .infinity)
                                .padding(.vertical, 14).background(p.fg).cornerRadius(12)
                        }
                    } else {
                        Text(theme?.subscription_choose_tier_title ?? "Сколько устройств")
                            .font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                        HStack(spacing: 8) {
                            tierChip(3, theme?.subscription_tier_3_label ?? "3 устройства", p)
                            tierChip(5, theme?.subscription_tier_5_label ?? "5 устройств", p)
                        }
                        Text(theme?.subscription_choose_plan_title ?? "Выберите тариф")
                            .font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg).padding(.top, 4)
                        ForEach(shown) { plan in
                            Button { Task { await vm.preparePayment(plan.id) } } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(plan.name).font(AppFont.text(14, weight: .semibold))
                                        Text("\(plan.days) дней").font(AppFont.text(11)).opacity(0.7)
                                    }
                                    Spacer()
                                    if vm.busyPlan == plan.id { ProgressView() }
                                    else { Text(plan.priceLabel).font(AppFont.text(14, weight: .medium)) }
                                }
                                .foregroundColor(p.bg)
                                .padding(.horizontal, 16).padding(.vertical, 14)
                                .background(p.fg).cornerRadius(12)
                            }
                            .disabled(vm.busyPlan != nil)
                        }
                        Text("Оплата откроется в браузере (YuMoney). После оплаты вернитесь в приложение.")
                            .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.45))
                    }
                }
            }
            .padding(16)
        }
        .task { await vm.loadPlans() }
        .onDisappear { vm.showSubscriptionShop = false }
        .alert(theme?.subscription_renewal_title ?? "Продление подписки", isPresented: Binding(
            get: { vm.renewalPreview != nil }, set: { if !$0 { vm.renewalPreview = nil } }
        )) {
            Button(theme?.subscription_renewal_confirm_label ?? "Перейти к оплате") {
                if let plan = vm.renewalPlan { Task { await vm.buy(plan) } }
                vm.renewalPreview = nil
            }
            Button("Отмена", role: .cancel) { vm.renewalPreview = nil }
        } message: { Text(vm.renewalPreview?.message ?? "") }
    }

    private var shown: [ShopPlan] {
        let all = vm.plans.isEmpty ? fallback : vm.plans
        let filtered = all.filter { $0.devices == vm.tier }
        return filtered.isEmpty ? all : filtered
    }

    private var fallback: [ShopPlan] {
        [
            ShopPlan(id: "monthly", name: "Месяц", price: 199, days: 30, devices: 3),
            ShopPlan(id: "two_months", name: "2 месяца", price: 359, days: 60, devices: 3),
            ShopPlan(id: "quarterly", name: "3 месяца", price: 478, days: 90, devices: 3),
            ShopPlan(id: "monthly_5", name: "Месяц", price: 330, days: 30, devices: 5),
            ShopPlan(id: "two_months_5", name: "2 месяца", price: 594, days: 60, devices: 5),
            ShopPlan(id: "quarterly_5", name: "3 месяца", price: 792, days: 90, devices: 5),
        ]
    }

    private var activeText: String {
        let plan = vm.profile?.subscription.plan_type
        let label: String = switch plan {
        case "trial": "Пробный период"
        case "test": "Тестовый режим"
        case "monthly": "Месяц · 3 устройства"
        case "two_months": "2 месяца · 3 устройства"
        case "quarterly": "3 месяца · 3 устройства"
        case "monthly_5": "Месяц · 5 устройств"
        case "two_months_5": "2 месяца · 5 устройств"
        case "quarterly_5": "3 месяца · 5 устройств"
        case "unlimited": "Бессрочно"
        default: plan ?? "—"
        }
        let unlimited = vm.profile?.is_admin == true || plan == "unlimited" || plan == "test"
        if unlimited { return "Тариф: \(label)\nБезлимитный доступ" }
        return "Тариф: \(label)\nОсталось: \(vm.profile?.subscription.days_left ?? 0) дней"
    }

    private func tierChip(_ count: Int, _ label: String, _ p: Palette) -> some View {
        let on = vm.tier == count
        return Button { vm.tier = count } label: {
            Text(label)
                .font(AppFont.text(13, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .foregroundColor(on ? p.bg : p.fg)
                .background(on ? p.fg : p.fg.opacity(0.08))
                .cornerRadius(12)
        }
    }
}

private struct ExclusionsPage: View {
    @EnvironmentObject var vm: MainViewModel
    @State private var pane = "sites"

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 10) {
            Text("Исключения").font(AppFont.text(14, weight: .bold)).foregroundColor(p.fg)
            Toggle(isOn: Binding(get: { vm.russianDirect }, set: { vm.setRussianDirect($0) })) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Российские сервисы мимо VPN").font(AppFont.text(14))
                    Text("Для всех приложений. Остальной трафик — через VPN.")
                        .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                }
            }.tint(p.fg).disabled(vm.russianBusy || vm.vpnState == .connecting || vm.vpnState == .disconnecting)
            if vm.russianDirect {
                Text("Другие исключения временно отключены. Ваши списки сохранены.")
                    .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
            }
            VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                chip("Сайты", on: pane == "sites", p: p) { pane = "sites" }
                chip("Приложения", on: pane == "apps", p: p) { pane = "apps" }
            }
            if pane == "sites" {
                Text("Домен или IP идут \(vm.sitesWhitelist ? "через VPN" : "мимо VPN") (ozon.ru, 1.2.3.4, 10.0.0.0/8). Домены резолвятся в момент подключения.")
                    .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                HStack(spacing: 8) {
                    chip("ЧС", on: !vm.sitesWhitelist, p: p) { vm.switchSitesMode(false) }
                    chip("БС", on: vm.sitesWhitelist, p: p) { vm.switchSitesMode(true) }
                }
                HStack {
                    TextField("домен или IP…", text: $vm.siteDraft)
                        .font(AppFont.text(14))
                        .textInputAutocapitalization(.never)
                        .padding(12)
                        .background(p.fg.opacity(0.05))
                        .cornerRadius(12)
                }
                Button("Добавить") { vm.addSite() }
                    .font(AppFont.text(13, weight: .semibold))
                    .foregroundColor(p.bg)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(p.fg)
                    .cornerRadius(12)
                    .disabled(vm.siteDraft.trimmingCharacters(in: .whitespaces).isEmpty)
                Text("\(vm.siteRules.count) / 100").font(AppFont.text(10)).foregroundColor(p.fg.opacity(0.4))
                if vm.siteRules.isEmpty {
                    Text("Список пуст").font(AppFont.text(13)).foregroundColor(p.fg.opacity(0.45))
                } else {
                    ScrollView {
                        VStack(spacing: 6) {
                            ForEach(vm.siteRules, id: \.self) { rule in
                                HStack {
                                    Text(rule).font(AppFont.text(13)).foregroundColor(p.fg)
                                    Spacer()
                                    Button { vm.removeSite(rule) } label: {
                                        Image(systemName: "xmark").foregroundColor(p.fg.opacity(0.45))
                                    }
                                }
                                .padding(.vertical, 6)
                            }
                        }
                    }
                }
            } else {
                Text("ЧС и БС приложений на Android выбирают, какие программы идут мимо VPN.")
                    .font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.55))
                Text("На iPhone система не даёт обычному VPN выбирать чужие приложения: в туннель входит весь трафик. Список сайтов выше работает.")
                    .font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.55))
                    .padding(.top, 4)
            }
            }.disabled(vm.russianDirect || vm.russianBusy).opacity(vm.russianDirect ? 0.35 : 1)
            Spacer()
        }
        .padding(.horizontal, 16)
    }

    private func chip(_ title: String, on: Bool, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(AppFont.text(13, weight: .semibold))
                .padding(.horizontal, 14).padding(.vertical, 8)
                .foregroundColor(on ? p.bg : p.fg)
                .background(on ? p.fg : p.fg.opacity(0.06))
                .cornerRadius(12)
        }
    }
}

private struct DnsPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let locked = vm.vpnState == .connected || vm.vpnState == .connecting
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("DNS").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                Text("Используйте рекомендуемый DNS или укажите свой. Применяется при следующем подключении VPN.")
                    .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.45))
                if locked {
                    Text("Отключите VPN перед сменой DNS.").font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.45))
                }
                option("Как на сервере", "Рекомендуется", on: vm.dnsPreset == "server", p: p) {
                    vm.saveDns(preset: "server")
                }
                .disabled(locked)
                option("Свой DNS", "до 3 адресов через запятую", on: vm.dnsPreset == "custom", p: p) {}
                    .disabled(true)
                TextField("1.1.1.1, 8.8.8.8", text: $vm.customDns)
                    .font(AppFont.text(14))
                    .textInputAutocapitalization(.never)
                    .padding(12)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                    .disabled(locked)
                Button("Сохранить свой DNS") { vm.saveDns(preset: "custom") }
                    .font(AppFont.text(13, weight: .semibold))
                    .foregroundColor(p.bg)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(p.fg)
                    .cornerRadius(12)
                    .disabled(locked)
                if !vm.dnsHint.isEmpty {
                    Text(vm.dnsHint).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.55))
                }
            }
            .padding(16)
        }
    }

    private func option(_ title: String, _ subtitle: String, on: Bool, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                    Text(subtitle).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.45))
                }
                Spacer()
                Image(systemName: on ? "largecircle.fill.circle" : "circle")
                    .foregroundColor(p.fg)
            }
        }
    }
}

private struct ServerPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let locked = vm.vpnState == .connected || vm.vpnState == .connecting
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("Выбор сервера").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                if locked {
                    Text("Переключение недоступно: VPN активен.").font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.7))
                }
                if !vm.serverHint.isEmpty {
                    Text(vm.serverHint).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.7))
                }
                ForEach(vm.servers) { server in
                    Button { Task { await vm.selectServer(server.key) } } label: {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(server.title).font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                                if let ip = server.public_ip, !ip.isEmpty {
                                    Text(ip).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.4))
                                }
                            }
                            Spacer()
                            Image(systemName: vm.selectedServer == server.key ? "largecircle.fill.circle" : "circle")
                                .foregroundColor(p.fg.opacity(locked ? 0.35 : 1))
                        }
                        .padding(.vertical, 8)
                    }
                    .disabled(locked)
                }
            }
            .padding(16)
        }
        .task { await vm.refreshServers() }
    }
}

private struct BonusesPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let theme = vm.theme
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text(theme?.bonuses_title ?? "Бонусы").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                Text(theme?.bonuses_intro_text ?? "").font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                Text(theme?.bonuses_referral_title ?? "Ваша ссылка").font(AppFont.text(13, weight: .semibold)).foregroundColor(p.fg)
                Text(theme?.bonuses_referral_hint ?? "").font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                Text(vm.referral?.referral_link ?? "…")
                    .font(AppFont.text(12))
                    .foregroundColor(p.fg)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                Button(theme?.bonuses_copy_link_label ?? "Копировать ссылку") {
                    if let link = vm.referral?.referral_link { vm.copy(link, ok: "Ссылка скопирована") }
                }
                .font(AppFont.text(13, weight: .semibold)).foregroundColor(p.bg)
                .frame(maxWidth: .infinity).padding(.vertical, 12).background(p.fg).cornerRadius(12)
                Button(theme?.bonuses_copy_code_label ?? "Копировать код") {
                    if let code = vm.referral?.referral_code { vm.copy(code, ok: "Код скопирован") }
                }
                .font(AppFont.text(13, weight: .semibold)).foregroundColor(p.fg)
                if let ref = vm.referral {
                    Text("Приглашено: \(ref.invited_count) · Награждено: \(ref.rewarded_count) · За 30 дней: \(ref.rewarded_last_30_days)/\(ref.monthly_reward_limit)")
                        .font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                }
                Text(theme?.bonuses_promo_title ?? "Промокод").font(AppFont.text(13, weight: .semibold)).foregroundColor(p.fg).padding(.top, 8)
                Text(theme?.bonuses_promo_hint ?? "").font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
                TextField("Промокод", text: $vm.promoCode)
                    .textInputAutocapitalization(.characters)
                    .font(AppFont.text(14))
                    .padding(12)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                Button("Проверить") { Task { await vm.checkPromo() } }
                    .font(AppFont.text(13, weight: .semibold)).foregroundColor(p.bg)
                    .frame(maxWidth: .infinity).padding(.vertical, 12).background(p.fg).cornerRadius(12)
                if !vm.promoMsg.isEmpty { Text(vm.promoMsg).font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.7)) }
                if !vm.copyMsg.isEmpty { Text(vm.copyMsg).font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.7)) }
            }
            .padding(16)
        }
        .task { await vm.loadReferral() }
    }
}

private struct DevicesPage: View {
    @EnvironmentObject var vm: MainViewModel
    @Environment(\.scenePhase) private var scenePhase
    @State private var rename: DeviceInfo?
    @State private var renameText = ""
    @State private var hint = ""
    @State private var deleteTarget: DeviceInfo?

    var body: some View {
        let p = vm.palette
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text("Сессии").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                Text(vm.profile?.sessionsBadge ?? "0/3").font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.5))
                Text("VPN онлайн: \(vm.profile?.devices.filter { vm.sessionOnline($0) }.count ?? 0) из \(vm.profile?.devices_count ?? 0)")
                    .font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.5))
                if !vm.sessionsError.isEmpty { Text(vm.sessionsError).font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.7)) }
                if !hint.isEmpty { Text(hint).font(AppFont.text(12)).foregroundColor(.red) }
                ForEach(vm.profile?.devices ?? []) { device in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Circle().fill(vm.sessionOnline(device) ? Color(red: 0.09, green: 0.64, blue: 0.29) : p.fg.opacity(0.25)).frame(width: 8, height: 8)
                            Text(device.device_name).font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
                            Spacer()
                            Text(device.device_type).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.4))
                        }
                        HStack {
                            Button("Переименовать") {
                                rename = device
                                renameText = device.device_name
                            }
                            .font(AppFont.text(12)).foregroundColor(p.link)
                            Button("Удалить") {
                                deleteTarget = device
                            }
                            .font(AppFont.text(12)).foregroundColor(.red)
                        }
                    }
                    .padding(.vertical, 8)
                }
            }
            .padding(16)
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await vm.refreshSessions()
                do { try await Task.sleep(nanoseconds: 10_000_000_000) } catch { return }
            }
        }
        .confirmationDialog("Удалить сессию?", isPresented: Binding(get: { deleteTarget != nil }, set: { if !$0 { deleteTarget = nil } })) {
            Button("Удалить", role: .destructive) {
                guard let id = deleteTarget?.id else { return }
                Task {
                    hint = await vm.deleteDevice(id) ?? ""
                    deleteTarget = nil
                }
            }
            Button("Отмена", role: .cancel) { deleteTarget = nil }
        }
        .alert("Приписать имя", isPresented: Binding(get: { rename != nil }, set: { if !$0 { rename = nil } })) {
            TextField("Имя", text: $renameText)
            Button("Сохранить") {
                guard let id = rename?.id else { return }
                Task {
                    if let err = await vm.renameDevice(id, renameText) { hint = err } else { hint = "" }
                    rename = nil
                }
            }
            Button("Отмена", role: .cancel) { rename = nil }
        }
    }
}

private struct SupportPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 16) {
            Text("Поддержка").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
            Text("По вопросам обратитесь через Telegram.")
                .font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.5))
            HStack(spacing: 24) {
                link("Канал", vm.theme?.telegram_channel_url.nilIfEmpty ?? "https://t.me/silentvpn3", p)
                link("Поддержка", vm.theme?.support_url.nilIfEmpty ?? "https://t.me/silentvpn3?direct", p)
            }
            if let privacy = vm.theme?.privacy_url.nilIfEmpty {
                Button("Политика") { open(privacy) }.font(AppFont.text(13)).foregroundColor(p.link)
            }
            if let terms = vm.theme?.terms_url.nilIfEmpty {
                Button("Условия") { open(terms) }.font(AppFont.text(13)).foregroundColor(p.link)
            }
            Spacer()
        }
        .padding(16)
    }

    private func link(_ title: String, _ url: String, _ p: Palette) -> some View {
        Button { open(url) } label: {
            VStack(spacing: 8) {
                Image(systemName: "paperplane.fill")
                    .font(AppFont.text(18))
                    .frame(width: 48, height: 48)
                    .background(p.fg.opacity(0.06))
                    .cornerRadius(16)
                    .foregroundColor(p.fg)
                Text(title).font(AppFont.text(11)).foregroundColor(p.fg.opacity(0.5))
            }
        }
    }

    private func open(_ raw: String) {
        guard let url = URL(string: raw) else { return }
        UIApplication.shared.open(url)
    }
}

private struct AboutPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
        VStack(alignment: .leading, spacing: 8) {
            Text("Silent VPN").font(AppFont.text(14, weight: .semibold)).foregroundColor(p.fg)
            Text("Версия \(version)\nWireGuard-туннель через VK TURN/DTLS")
                .font(AppFont.text(12)).foregroundColor(p.fg.opacity(0.5))
            Spacer()
        }
        .padding(16)
    }
}
