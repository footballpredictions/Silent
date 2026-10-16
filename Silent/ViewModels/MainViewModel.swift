import SwiftUI
import UIKit

enum MenuPage: String {
    case root, subscription, exclusions, dns, server, bonuses, devices, support, about
}

enum PaymentUi { case idle, waiting, success, failed, timeout }

@MainActor
final class MainViewModel: ObservableObject {
    @Published var vpnState: VpnState = .disconnected
    @Published var profile: UserProfile?
    @Published var theme: ThemeData?
    @Published var errorMessage: String?
    @Published var loggedIn = false
    @Published var authLoading = false
    @Published var authError: String?
    @Published var regNeedMail = false
    @Published var forgotSent = false
    @Published var darkMode = LocalStore.appearanceDark

    @Published var menuOpen = false
    @Published var menuPage: MenuPage = .root

    @Published var plans: [ShopPlan] = []
    @Published var tier = 3
    @Published var payment: PaymentUi = .idle
    @Published var busyPlan: String?
    @Published var paymentError: String?
    @Published var showSubscriptionShop = false
    @Published var renewalPreview: PaymentPreview?
    @Published var renewalPlan: String?

    @Published var referral: ReferralInfo?
    @Published var promoCode = ""
    @Published var promoMsg = ""
    @Published var copyMsg = ""

    @Published var dnsPreset = LocalStore.dnsPreset
    @Published var customDns = LocalStore.customDns
    @Published var dnsHint = ""

    @Published var servers: [VpnServer] = []
    @Published var selectedServer = LocalStore.preferredServer
    @Published var serverHint = ""

    @Published var siteRules: [String] = LocalStore.siteRules
    @Published var sitesWhitelist = LocalStore.sitesWhitelist
    @Published var siteDraft = ""
    @Published var russianDirect = RussianServices.enabled
    @Published var russianBusy = false

    private let api = APIService.shared
    private var pollTask: Task<Void, Never>?
    private let vpn = VpnManager.shared
    private var siteRoutingUpdate: Task<Void, Never>?

    var palette: Palette { Palette.resolve(theme: theme, dark: darkMode) }
    var hasAccess: Bool { profile?.is_admin == true || profile?.subscription.is_active == true }

    init() {
        theme = api.cachedTheme()
        loggedIn = api.isLoggedIn
        Task {
            await vpn.refresh()
            vpnState = vpn.state
            await loadInitialData()
        }
        Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                if self.vpnState != self.vpn.state {
                    self.vpnState = self.vpn.state
                    if self.vpn.state == .disconnected, let err = self.vpn.readError() {
                        self.errorMessage = err
                    }
                }
            }
        }
    }

    func toggleAppearance() {
        darkMode.toggle()
        LocalStore.appearanceDark = darkMode
    }

    func loadInitialData() async {
        theme = (try? await api.getTheme()) ?? theme
        guard api.isLoggedIn else { return }
        loggedIn = true
        profile = try? await api.getProfile()
        await refreshServers()
    }

    func login(email: String, password: String, remember: Bool) async {
        authLoading = true
        authError = nil
        defer { authLoading = false }
        do {
            _ = try await api.login(email: email, password: password)
            LocalStore.rememberMe = remember
            if remember {
                LocalStore.rememberedEmail = email
                LocalStore.rememberedPassword = password
            } else {
                LocalStore.rememberedEmail = ""
                LocalStore.rememberedPassword = ""
            }
            loggedIn = true
            await loadInitialData()
        } catch {
            authError = error.localizedDescription
        }
    }

    func register(email: String, password: String, code: String, remember: Bool) async {
        authLoading = true
        authError = nil
        regNeedMail = false
        defer { authLoading = false }
        do {
            let entered = try await api.register(email: email, password: password, referralOrPromo: code)
            if remember {
                LocalStore.rememberMe = true
                LocalStore.rememberedEmail = email
                LocalStore.rememberedPassword = password
            }
            if entered {
                loggedIn = true
                await loadInitialData()
            } else {
                regNeedMail = true
            }
        } catch {
            authError = error.localizedDescription
        }
    }

    func forgot(email: String) async {
        authLoading = true
        authError = nil
        defer { authLoading = false }
        do {
            try await api.forgotPassword(email: email)
            forgotSent = true
        } catch {
            authError = error.localizedDescription
        }
    }

    func logout() {
        Task {
            if vpnState == .connected || vpnState == .connecting {
                await vpn.disconnect()
            }
            await api.logoutSession()
            profile = nil
            loggedIn = false
            vpnState = .disconnected
            menuOpen = false
            menuPage = .root
            payment = .idle
        }
    }

    func toggleVPN() async {
        errorMessage = nil
        if vpnState == .connected || vpnState == .connecting {
            try? await api.disconnect()
            await vpn.disconnect()
            vpnState = .disconnected
            return
        }
        guard hasAccess else {
            menuOpen = false
            menuPage = .subscription
            return
        }
        vpnState = .connecting
        do {
            let cfg = try await api.registerDevice(name: UIDevice.current.name, preferredServer: selectedServer)
            try await api.connect(preferredServer: selectedServer)
            let tunnel = makeTunnel(cfg)
            try await vpn.connect(tunnel)
            profile = try? await api.getProfile()
        } catch {
            vpnState = .disconnected
            errorMessage = error.localizedDescription
            await vpn.disconnect()
        }
    }

    private func makeTunnel(_ cfg: VpnConfig) -> TunnelConfig {
        let dns: [String]
        if dnsPreset == "custom", let custom = DnsInput.sanitize(customDns) {
            dns = custom
        } else {
            dns = cfg.wg_dns.split { $0 == "," || $0 == " " }.map { String($0) }.filter { !$0.isEmpty }
        }
        let workers = max(9, min(cfg.stream_count, 27))
        return TunnelConfig(
            deviceId: cfg.device_id,
            serverIP: cfg.server_ip,
            serverPort: cfg.server_port,
            password: cfg.wdtt_password,
            hashes: cfg.vk_hashes,
            workers: workers,
            privateKey: cfg.wg_private_key,
            publicKey: cfg.server_public_key,
            address: cfg.wg_address,
            dns: dns,
            mtu: ServerCatalog.mtu(slot: selectedServer, ip: cfg.server_ip),
            excludeCIDRs: siteRules,
            sitesWhitelist: sitesWhitelist,
            russian: RussianServices.policy(enabled: russianDirect)
        )
    }

    func loadPlans() async {
        plans = (try? await api.getPlans()) ?? plans
    }

    func buy(_ planId: String) async {
        guard busyPlan == nil else { return }
        busyPlan = planId
        paymentError = nil
        defer { busyPlan = nil }
        do {
            let res = try await api.initPayment(plan: planId)
            guard let url = URL(string: res.url) else {
                paymentError = "Нет ссылки на оплату"
                return
            }
            payment = .waiting
            await UIApplication.shared.open(url)
            startPoll(res.label)
        } catch {
            payment = .failed
            paymentError = error.localizedDescription
        }
    }

    func preparePayment(_ planId: String) async {
        guard busyPlan == nil else { return }
        guard profile?.subscription.is_active == true else { await buy(planId); return }
        busyPlan = planId
        defer { busyPlan = nil }
        do {
            if let cached = profile?.payment_previews?[planId], cached.isFresh {
                renewalPreview = cached
            } else {
                renewalPreview = try await api.previewPayment(plan: planId)
            }
            renewalPlan = planId
        } catch {
            payment = .failed
            paymentError = error.localizedDescription
        }
    }

    func startPoll(_ label: String) {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            for _ in 0..<45 {
                try? await Task.sleep(nanoseconds: 4_000_000_000)
                if Task.isCancelled { return }
                guard let self else { return }
                if let status = try? await self.api.paymentStatus(label: label) {
                    if status.status == "completed" && status.subscription_applied != false {
                        guard let fresh = try? await self.api.getProfile() else { continue }
                        if Task.isCancelled { return }
                        guard fresh.is_admin || (fresh.subscription.is_active &&
                            fresh.subscription.plan_type != "trial" &&
                            fresh.subscription.plan_type != "test" &&
                            (status.plan_type == nil || fresh.subscription.plan_type == status.plan_type)) else { continue }
                        self.profile = fresh
                        self.payment = .success
                        self.showSubscriptionShop = false
                        return
                    }
                    if status.status == "failed" || status.status == "expired" || status.status == "cancelled" {
                        self.payment = .failed
                        return
                    }
                }
            }
            self?.payment = .timeout
        }
    }

    func resetPayment() {
        pollTask?.cancel()
        payment = .idle
        paymentError = nil
    }

    func onPaymentReturn() async {
        if let fresh = try? await api.getProfile() { profile = fresh }
    }

    func loadReferral() async {
        referral = try? await api.referral()
    }

    func checkPromo() async {
        let code = promoCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else { return }
        do {
            let res = try await api.checkPromo(code: code, plan: tier == 5 ? "monthly_5" : "monthly")
            var text = "Скидка \(Int(res.discount_percent))%"
            if res.extra_days > 0 { text += ", +\(res.extra_days) дн." }
            text += " · \(Int(res.discounted_price)) ₽ вместо \(Int(res.original_price)) ₽"
            promoMsg = text
        } catch {
            promoMsg = error.localizedDescription
        }
    }

    func copy(_ text: String, ok: String) {
        UIPasteboard.general.string = text
        copyMsg = ok
    }

    func saveDns(preset: String) {
        if vpnState == .connected || vpnState == .connecting {
            dnsHint = "Отключите VPN перед сменой DNS."
            return
        }
        if preset == "custom" {
            guard DnsInput.sanitize(customDns) != nil else {
                dnsHint = "Нужны IP-адреса, например 1.1.1.1, до 3 штук."
                return
            }
        }
        dnsPreset = preset
        LocalStore.dnsPreset = preset
        LocalStore.customDns = customDns
        dnsHint = "Применится при следующем подключении."
    }

    func refreshServers() async {
        let fallback = ServerCatalog.slots.map {
            VpnServer(key: $0.key, title: $0.title, public_ip: ServerCatalog.bakedIP($0.key), wdtt_port: nil, online_count: nil)
        }
        if let body = try? await api.fetchServers() {
            var byKey: [String: VpnServer] = [:]
            for item in body.servers {
                byKey[item.key.lowercased()] = item
            }
            servers = ServerCatalog.slots.map { slot in
                if let known = byKey.removeValue(forKey: slot.key) {
                    let title = (slot.key == "server4" && (known.title.isEmpty || known.title == "Сервер 4")) ? slot.title : (known.title.isEmpty ? slot.title : known.title)
                    return VpnServer(key: slot.key, title: title, public_ip: known.public_ip, wdtt_port: known.wdtt_port, online_count: known.online_count)
                }
                return fallback.first { $0.key == slot.key }!
            }
            if let selected = body.selected_server?.lowercased(), selected.hasPrefix("server") {
                selectedServer = selected
                LocalStore.preferredServer = selected
            }
        } else if servers.isEmpty {
            servers = fallback
        }
    }

    func selectServer(_ key: String) async {
        if vpnState == .connected || vpnState == .connecting {
            serverHint = "Отключите VPN перед сменой сервера."
            return
        }
        do {
            _ = try await api.selectServer(key)
            selectedServer = key
            LocalStore.preferredServer = key
            serverHint = ""
            await refreshServers()
        } catch {
            selectedServer = key
            LocalStore.preferredServer = key
            serverHint = error.localizedDescription
        }
    }

    func addSite() {
        guard !russianDirect else { return }
        let rule = siteDraft.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !rule.isEmpty else { return }
        if siteRules.contains(rule) { siteDraft = ""; return }
        guard siteRules.count < 100 else { return }
        siteRules.append(rule)
        siteDraft = ""
        LocalStore.siteRules = siteRules
        applySiteRouting()
    }

    func removeSite(_ rule: String) {
        guard !russianDirect else { return }
        siteRules.removeAll { $0 == rule }
        LocalStore.siteRules = siteRules
        applySiteRouting()
    }

    func switchSitesMode(_ whitelist: Bool) {
        guard !russianDirect else { return }
        guard sitesWhitelist != whitelist else { return }
        sitesWhitelist = whitelist
        LocalStore.sitesWhitelist = whitelist
        siteRules = LocalStore.siteRules
        siteDraft = ""
        applySiteRouting()
    }

    func setRussianDirect(_ enabled: Bool) {
        guard !russianBusy, vpnState != .connecting, vpnState != .disconnecting, let policy = RussianServices.policy(enabled: enabled) else { return }
        let old = russianDirect
        let rules = siteRules
        let whitelist = sitesWhitelist
        russianBusy = true
        russianDirect = enabled
        RussianServices.enabled = enabled
        let previous = siteRoutingUpdate
        siteRoutingUpdate = Task {
            await previous?.value
            do { try await vpn.updateSiteRouting(rules: rules, whitelist: whitelist, russian: policy) }
            catch {
                russianDirect = old
                RussianServices.enabled = old
                errorMessage = error.localizedDescription
            }
            russianBusy = false
        }
    }

    private func applySiteRouting() {
        let rules = siteRules
        let whitelist = sitesWhitelist
        let russian = RussianServices.policy(enabled: russianDirect)
        let previous = siteRoutingUpdate
        siteRoutingUpdate = Task {
            await previous?.value
            do { try await vpn.updateSiteRouting(rules: rules, whitelist: whitelist, russian: russian) }
            catch { errorMessage = error.localizedDescription }
        }
    }

    func renameDevice(_ id: String, _ name: String) async -> String? {
        do {
            try await api.renameDevice(id: id, name: name)
            profile = try? await api.getProfile()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func deleteDevice(_ id: String) async -> String? {
        do {
            try await api.deleteDevice(id: id)
            profile = try? await api.getProfile()
            return nil
        } catch {
            return error.localizedDescription
        }
    }
}
