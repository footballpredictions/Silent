import SwiftUI
import UIKit

struct MenuPageHost: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 0) {
            Button { vm.menuPage = .root; vm.menuOpen = true } label: {
                Label("Назад", systemImage: "chevron.left")
                    .font(.body)
                    .foregroundColor(p.fg)
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .padding(.horizontal, 16)
            .padding(.vertical, 4)
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
                case .preparing:
                    ProgressView("Проверяем доступность ЮMoney…")
                        .foregroundStyle(p.fg)
                    Button(theme?.payment_cancel_button_text ?? "Отмена") { vm.resetPayment() }
                        .font(.subheadline).foregroundColor(p.link)
                case .waiting:
                    Text(theme?.payment_waiting_title ?? "").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                    Text(theme?.payment_waiting_text ?? "").font(.subheadline).foregroundColor(p.fg.opacity(0.55))
                    Button(theme?.payment_cancel_button_text ?? "Отмена") { vm.resetPayment() }
                        .font(.subheadline).foregroundColor(p.link)
                case .success:
                    Text(theme?.payment_success_title ?? "").font(.headline.weight(.semibold))
                        .foregroundStyle(p.success).shadow(color: p.successGlow, radius: 4)
                    Text(theme?.payment_success_text ?? "").font(.subheadline).foregroundColor(p.fg.opacity(0.55))
                    Button("Закрыть") { vm.resetPayment() }.font(.subheadline).foregroundColor(p.link)
                case .failed:
                    Text(theme?.payment_failed_title ?? "").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                    Text(vm.paymentError ?? theme?.payment_failed_text ?? "").font(.subheadline).foregroundColor(.red)
                    Button(theme?.payment_retry_button_text ?? "Попробовать снова") { vm.resetPayment() }
                        .font(.subheadline).foregroundColor(p.link)
                case .timeout:
                    Text(theme?.payment_timeout_title ?? "").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                    Text(theme?.payment_timeout_text ?? "").font(.subheadline).foregroundColor(p.fg.opacity(0.55))
                    Button(theme?.payment_retry_button_text ?? "Попробовать снова") { vm.resetPayment() }
                        .font(.subheadline).foregroundColor(p.link)
                case .idle:
                    Text("Подписка и оплата обновляются автоматически при включённом VPN.")
                        .font(.footnote).foregroundColor(p.fg.opacity(0.65))
                    if (vm.profile?.subscription.is_active == true || vm.profile?.is_admin == true) && !vm.showSubscriptionShop {
                        Text("Подписка активна").font(.headline.weight(.semibold))
                            .foregroundStyle(p.success).shadow(color: p.successGlow, radius: 4)
                        Text(activeText).font(.subheadline).foregroundColor(p.fg.opacity(0.5))
                        if vm.profile?.is_admin != true && !["unlimited", "test"].contains(vm.profile?.subscription.plan_type ?? "") {
                            Button(theme?.subscription_pay_early_label ?? "Оплатить заранее") {
                                vm.tier = vm.profile?.max_devices == 5 ? 5 : 3
                                vm.showSubscriptionShop = true
                            }.font(.headline.weight(.semibold))
                                .foregroundColor(p.bg).frame(maxWidth: .infinity)
                                .padding(.vertical, 14).background(p.fg).cornerRadius(12)
                        }
                    } else {
                        Text(theme?.subscription_choose_tier_title ?? "Сколько устройств")
                            .font(.headline.weight(.semibold)).foregroundColor(p.fg)
                        HStack(spacing: 8) {
                            tierChip(3, theme?.subscription_tier_3_label ?? "3 устройства", p)
                            tierChip(5, theme?.subscription_tier_5_label ?? "5 устройств", p)
                        }
                        Text(theme?.subscription_choose_plan_title ?? "Выберите тариф")
                            .font(.headline.weight(.semibold)).foregroundColor(p.fg).padding(.top, 4)
                        ForEach(shown) { plan in
                            Button { Task { await vm.preparePayment(plan.id) } } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(plan.name).font(.headline.weight(.semibold))
                                        Text("\(plan.days) дней").font(.footnote).opacity(0.7)
                                    }
                                    Spacer()
                                    if vm.busyPlan == plan.id { ProgressView() }
                                    else {
                                        TimelineView(.periodic(from: .now, by: 30)) { _ in
                                            Text(plan.priceLabel(preview: vm.profile?.payment_previews?[plan.id]))
                                                .font(.body.weight(.medium))
                                        }
                                    }
                                }
                                .foregroundColor(p.bg)
                                .padding(.horizontal, 16).padding(.vertical, 14)
                                .background(p.fg).cornerRadius(12)
                            }
                            .disabled(vm.busyPlan != nil)
                        }
                        Text("Оплата откроется в браузере (YuMoney). После оплаты вернитесь в приложение.")
                            .font(.footnote).foregroundColor(p.fg.opacity(0.65))
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
                .font(.subheadline.weight(.semibold))
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

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 10) {
            Text("Исключения").font(.headline.weight(.bold)).foregroundColor(p.fg)
            Toggle(isOn: Binding(get: { vm.russianDirect }, set: { vm.setRussianDirect($0) })) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Российские сервисы мимо VPN").font(.body)
                    Text("Для всех приложений. Остальной трафик — через VPN.")
                        .font(.footnote).foregroundColor(p.fg.opacity(0.5))
                }
            }.tint(p.switchOn).disabled(vm.routingControlsLocked)
            if vm.russianDirect {
                if vm.russianListReceived {
                    Text("Список получен")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(p.success)
                        .shadow(color: p.successGlow, radius: 4)
                }
                Text("Другие исключения временно отключены. Ваши списки сохранены.")
                    .font(.footnote).foregroundColor(p.fg.opacity(0.5))
            }
            VStack(alignment: .leading, spacing: 10) {
                Text("Домен или IP идут \(vm.sitesWhitelist ? "через VPN" : "мимо VPN") (ozon.ru, 1.2.3.4, 10.0.0.0/8). Домены резолвятся в момент подключения.")
                    .font(.footnote).foregroundColor(p.fg.opacity(0.5))
                HStack(spacing: 8) {
                    chip("ЧС", on: !vm.sitesWhitelist, p: p) { vm.switchSitesMode(false) }
                    chip("БС", on: vm.sitesWhitelist, p: p) { vm.switchSitesMode(true) }
                }
                HStack {
                    TextField("домен или IP…", text: $vm.siteDraft)
                        .font(.body)
                        .textInputAutocapitalization(.never)
                        .padding(12)
                        .background(p.fg.opacity(0.05))
                        .cornerRadius(12)
                }
                Button("Добавить") { vm.addSite() }
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(p.bg)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(p.fg)
                    .cornerRadius(12)
                    .disabled(vm.siteDraft.trimmingCharacters(in: .whitespaces).isEmpty)
                Text("\(vm.siteRules.count) / 100").font(.footnote).foregroundColor(p.fg.opacity(0.65))
                if vm.siteRules.isEmpty {
                    Text("Список пуст").font(.subheadline).foregroundColor(p.fg.opacity(0.65))
                } else {
                    ScrollView {
                        VStack(spacing: 6) {
                            ForEach(vm.siteRules, id: \.self) { rule in
                                HStack {
                                    Text(rule).font(.subheadline).foregroundColor(p.fg)
                                    Spacer()
                                    Button { vm.removeSite(rule) } label: {
                                        Image(systemName: "xmark").foregroundColor(p.fg.opacity(0.65))
                                    }
                                }
                                .padding(.vertical, 6)
                            }
                        }
                    }
                }
            }.disabled(vm.russianDirect || vm.routingControlsLocked).opacity(vm.russianDirect ? 0.35 : 1)
            Spacer()
        }
        .padding(.horizontal, 16)
        .task(id: vm.russianDirect && vm.vpnState == .connected && !vm.russianBusy) {
            await vm.updateRussianListStatus()
            guard vm.russianDirect, vm.vpnState == .connected, !vm.russianBusy else { return }
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 1_500_000_000) } catch { return }
                await vm.updateRussianListStatus()
            }
        }
    }

    private func chip(_ title: String, on: Bool, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.subheadline.weight(.semibold))
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
        let locked = vm.vpnState != .disconnected
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("DNS").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                Text("Используйте рекомендуемый DNS или укажите свой. Применяется при следующем подключении VPN.")
                    .font(.footnote).foregroundColor(p.fg.opacity(0.65))
                if locked {
                    Text("Отключите VPN перед сменой DNS.").font(.footnote).foregroundColor(p.fg.opacity(0.65))
                }
                option("Как на сервере", "Рекомендуется", on: vm.dnsPreset == "server", p: p) {
                    vm.saveDns(preset: "server")
                }
                .disabled(locked)
                option("Свой DNS", "до 3 адресов через запятую", on: vm.dnsPreset == "custom", p: p) {}
                    .disabled(true)
                TextField("1.1.1.1, 8.8.8.8", text: $vm.customDns)
                    .font(.body)
                    .textInputAutocapitalization(.never)
                    .padding(12)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                    .disabled(locked)
                Button("Сохранить свой DNS") { vm.saveDns(preset: "custom") }
                    .font(.subheadline.weight(.semibold))
                    .foregroundColor(p.bg)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(p.fg)
                    .cornerRadius(12)
                    .disabled(locked)
                if !vm.dnsHint.isEmpty {
                    Text(vm.dnsHint).font(.footnote).foregroundColor(p.fg.opacity(0.55))
                }
            }
            .padding(16)
        }
    }

    private func option(_ title: String, _ subtitle: String, on: Bool, p: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.headline.weight(.semibold)).foregroundColor(p.fg)
                    Text(subtitle).font(.footnote).foregroundColor(p.fg.opacity(0.65))
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
        let locked = vm.vpnState != .disconnected
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                Text("Выбор сервера").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                if locked {
                    Text("Переключение недоступно: VPN активен.").font(.footnote).foregroundColor(p.fg.opacity(0.7))
                }
                if !vm.serverHint.isEmpty {
                    Text(vm.serverHint).font(.footnote).foregroundColor(p.fg.opacity(0.7))
                }
                ForEach(vm.servers) { server in
                    let selected = vm.selectedServer == server.key
                    Button { vm.selectServer(server.key) } label: {
                        HStack {
                            Text(server.title).font(.body.weight(.medium)).foregroundColor(p.fg)
                            Spacer()
                            Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                                .foregroundColor(p.fg.opacity(locked ? 0.35 : 1))
                        }
                        .padding(.horizontal, 12)
                        .frame(minHeight: 48)
                        .background(p.fg.opacity(selected ? 0.07 : 0.035), in: RoundedRectangle(cornerRadius: 12))
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(locked || selected)
                    .accessibilityAddTraits(selected ? .isSelected : [])
                }
            }
            .padding(16)
        }
    }
}

private struct BonusesPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        let theme = vm.theme
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Text(theme?.bonuses_title ?? "Бонусы").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                Text(theme?.bonuses_intro_text ?? "").font(.footnote).foregroundColor(p.fg.opacity(0.5))
                Text(theme?.bonuses_referral_title ?? "Ваша ссылка").font(.subheadline.weight(.semibold)).foregroundColor(p.fg)
                Text(theme?.bonuses_referral_hint ?? "").font(.footnote).foregroundColor(p.fg.opacity(0.5))
                Text(vm.referral?.referral_link ?? "…")
                    .font(.subheadline)
                    .foregroundColor(p.fg)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                Button(theme?.bonuses_copy_link_label ?? "Копировать ссылку") {
                    if let link = vm.referral?.referral_link { vm.copy(link, ok: "Ссылка скопирована") }
                }
                .font(.subheadline.weight(.semibold)).foregroundColor(p.bg)
                .frame(maxWidth: .infinity).padding(.vertical, 12).background(p.fg).cornerRadius(12)
                Button(theme?.bonuses_copy_code_label ?? "Копировать код") {
                    if let code = vm.referral?.referral_code { vm.copy(code, ok: "Код скопирован") }
                }
                .font(.subheadline.weight(.semibold)).foregroundColor(p.fg)
                if let ref = vm.referral {
                    Text("Приглашено: \(ref.invited_count) · Награждено: \(ref.rewarded_count) · За 30 дней: \(ref.rewarded_last_30_days)/\(ref.monthly_reward_limit)")
                        .font(.footnote).foregroundColor(p.fg.opacity(0.5))
                }
                Text(theme?.bonuses_promo_title ?? "Промокод").font(.subheadline.weight(.semibold)).foregroundColor(p.fg).padding(.top, 8)
                Text(theme?.bonuses_promo_hint ?? "").font(.footnote).foregroundColor(p.fg.opacity(0.5))
                TextField("Промокод", text: $vm.promoCode)
                    .textInputAutocapitalization(.characters)
                    .font(.body)
                    .padding(12)
                    .background(p.fg.opacity(0.05))
                    .cornerRadius(12)
                Button("Проверить") { Task { await vm.checkPromo() } }
                    .font(.subheadline.weight(.semibold)).foregroundColor(p.bg)
                    .frame(maxWidth: .infinity).padding(.vertical, 12).background(p.fg).cornerRadius(12)
                if !vm.promoMsg.isEmpty { Text(vm.promoMsg).font(.subheadline).foregroundColor(p.fg.opacity(0.7)) }
                if !vm.copyMsg.isEmpty { Text(vm.copyMsg).font(.subheadline).foregroundColor(p.fg.opacity(0.7)) }
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
                Text("Сессии").font(.headline.weight(.semibold)).foregroundColor(p.fg)
                Text("VPN онлайн: \(vm.profile?.devices.filter { vm.sessionOnline($0) }.count ?? 0) из \(vm.profile?.devices_count ?? 0)")
                    .font(.subheadline).foregroundColor(p.fg.opacity(0.5))
                Text("Занято слотов: \(vm.profile?.devices_count ?? 0) из \(slotLimit)")
                    .font(.subheadline).foregroundColor(p.fg.opacity(0.5))
                if !vm.sessionsError.isEmpty { Text(vm.sessionsError).font(.subheadline).foregroundColor(p.fg.opacity(0.7)) }
                if !hint.isEmpty { Text(hint).font(.subheadline).foregroundColor(.red) }
                ForEach(vm.profile?.devices ?? []) { device in
                    deviceRow(device, palette: p)
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
        .confirmationDialog("Удалить сессию?", isPresented: Binding(get: { deleteTarget != nil }, set: { if !$0 { deleteTarget = nil } }), presenting: deleteTarget) { device in
            Button("Удалить", role: .destructive) {
                Task { hint = await vm.deleteDevice(device.id) ?? "" }
            }
            Button("Отмена", role: .cancel) { deleteTarget = nil }
        }
        .alert("Переименовать устройство", isPresented: Binding(get: { rename != nil }, set: { if !$0 { rename = nil } }), presenting: rename) { device in
            TextField("Имя", text: $renameText)
            Button("Сохранить") {
                let name = renameText
                Task { hint = await vm.renameDevice(device.id, name) ?? "" }
            }
            Button("Отмена", role: .cancel) { rename = nil }
        }
    }

    private var slotLimit: String {
        guard let profile = vm.profile else { return "3" }
        return profile.is_admin || profile.max_devices <= 0 ? "∞" : String(profile.max_devices)
    }

    private func deviceRow(_ device: DeviceInfo, palette: Palette) -> some View {
        let online = vm.sessionOnline(device)
        return VStack(spacing: 0) {
            HStack(spacing: 8) {
                Circle()
                    .fill(online ? Color(red: 0.09, green: 0.64, blue: 0.29) : palette.fg.opacity(0.25))
                    .frame(width: 10, height: 10)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(device.platformLabel).font(.body.weight(.medium)).foregroundStyle(palette.fg)
                    if let name = device.customLabel {
                        Text(name).font(.subheadline).foregroundStyle(palette.fg.opacity(0.65))
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityValue(online ? "VPN онлайн" : "VPN отключён")
                Spacer(minLength: 0)
                deviceAction("pencil", label: "Переименовать устройство", palette: palette) {
                    renameText = device.customLabel ?? ""
                    rename = device
                }
                deviceAction("xmark", label: "Удалить сессию", palette: palette) {
                    deleteTarget = device
                }
            }
            .padding(.vertical, 6)
            Divider().overlay(palette.fg.opacity(0.12))
        }
    }

    private func deviceAction(_ icon: String, label: String, palette: Palette, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.body.weight(.medium))
                .foregroundStyle(palette.fg.opacity(0.65))
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

private struct SupportPage: View {
    @EnvironmentObject var vm: MainViewModel

    var body: some View {
        let p = vm.palette
        VStack(alignment: .leading, spacing: 16) {
            Text("Поддержка").font(.headline.weight(.semibold)).foregroundColor(p.fg)
            Text("По вопросам обратитесь через Telegram.")
                .font(.subheadline).foregroundColor(p.fg.opacity(0.5))
            HStack(spacing: 24) {
                link("Канал", vm.theme?.telegram_channel_url.nilIfEmpty ?? "https://t.me/silentvpn3", p)
                link("Поддержка", vm.theme?.support_url.nilIfEmpty ?? "https://t.me/silentvpn3?direct", p)
            }
            if let privacy = vm.theme?.privacy_url.nilIfEmpty {
                Button("Политика") { open(privacy) }.font(.subheadline).foregroundColor(p.link)
            }
            if let terms = vm.theme?.terms_url.nilIfEmpty {
                Button("Условия") { open(terms) }.font(.subheadline).foregroundColor(p.link)
            }
            Spacer()
        }
        .padding(16)
    }

    private func link(_ title: String, _ url: String, _ p: Palette) -> some View {
        Button { open(url) } label: {
            VStack(spacing: 8) {
                Image(systemName: "paperplane.fill")
                    .font(.title3)
                    .frame(width: 48, height: 48)
                    .background(p.fg.opacity(0.06))
                    .cornerRadius(16)
                    .foregroundColor(p.fg)
                Text(title).font(.footnote).foregroundColor(p.fg.opacity(0.5))
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
            Text("Silent VPN").font(.headline.weight(.semibold)).foregroundColor(p.fg)
            Text("Версия \(version)\nWireGuard-туннель через VK TURN/DTLS")
                .font(.subheadline).foregroundColor(p.fg.opacity(0.5))
            Spacer()
        }
        .padding(16)
    }
}
