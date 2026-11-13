import SwiftUI
import UIKit
import Combine

enum MenuPage: String {
    case root, subscription, exclusions, dns, server, bonuses, devices, support, about
}

enum PaymentUi { case idle, waiting, success, failed, timeout }

@MainActor
final class MainViewModel: ObservableObject {
    @Published var vpnState: VpnState = .disconnected
    @Published var profile: UserProfile?
    @Published var sessionsError = ""
    private var sessionsVersion = 0
    private var sessionsFetching = false
    private var sessionsMutation = false
    @Published var theme: ThemeData?
    @Published var errorMessage: String?
    @Published var loggedIn = false
    @Published var authLoading = false
    @Published var authLoadingTitle = "Вход…"
    @Published var authError: String?
    @Published var bootstrapDeadline: Date?
    @Published var bootstrapStarting = false
    @Published var connectionLog: [String] = []
    @Published private(set) var connectionStage: ConnectionStage?
    @Published private(set) var bootstrapStage: ConnectionStage?
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
    private var vpnObserver: AnyCancellable?
    private var bootstrapActive = false
    private var bootstrapAttempted = false
    private var vpnActionInProgress = false
    private var connectedAt: Date?
    private var profileLoading = false

    private let bootstrapHash = (Bundle.main.object(forInfoDictionaryKey: "SilentBootstrapVKHash") as? String ?? "")
        .trimmingCharacters(in: .whitespacesAndNewlines)

    var palette: Palette { Palette.resolve(theme: theme, dark: darkMode) }
    var hasAccess: Bool { profile?.is_admin == true || profile?.subscription.is_active == true }
    var sessionDeviceId: String? {
        AppIdentity.readTunnelConfig()?.deviceId
    }

    func sessionOnline(_ device: DeviceInfo) -> Bool {
        device.is_connected || (device.id == sessionDeviceId && vpnState == .connected)
    }

    init() {
        theme = api.cachedTheme()
        vpnObserver = vpn.$state.removeDuplicates().sink { [weak self] state in
            self?.onVPNStateChanged(state)
        }
        Task {
            if AppIdentity.readTunnelConfig()?.bootstrapDuration != nil {
                bootstrapActive = true
            }
            await vpn.refresh()
            if bootstrapActive && (!api.isLoggedIn || vpn.state == .disconnected) {
                await stopBootstrap()
            } else if !api.isLoggedIn, vpn.state == .connected || vpn.state == .connecting {
                await vpn.disconnect()
            }
            await loadInitialData()
        }
    }

    private func onVPNStateChanged(_ state: VpnState) {
        if bootstrapActive {
            if state == .disconnected, !bootstrapStarting {
                bootstrapActive = false
                bootstrapDeadline = nil
                authError = vpn.readError()
                logConnection(authError ?? "Временный VPN отключён")
            }
            return
        }
        guard !vpnActionInProgress, state != vpnState else { return }
        let wasActive = vpnState == .connected || vpnState == .connecting || connectedAt != nil
        vpnState = state
        if state == .connected, connectedAt == nil { connectedAt = Date() }
        if state == .disconnected, wasActive {
            let uptime = connectedAt.map { max(0, Int(Date().timeIntervalSince($0))) }
            connectedAt = nil
            let reason = vpn.readError() ?? "Соединение VPN завершено"
            let duration = uptime.map { " · \($0) с" } ?? ""
            errorMessage = reason
            logConnection(reason + duration)
            Task {
                if let code = await vpn.lastDisconnectCode(), vpnState == .disconnected {
                    logConnection("Код отключения iOS: \(code)")
                }
            }
        }
    }

    private func logConnection(_ text: String) {
        let time = Date().formatted(date: .omitted, time: .standard)
        connectionLog.append("\(time)  \(text)")
        if connectionLog.count > 30 { connectionLog.removeFirst() }
    }

    private func startBootstrap() async {
        guard !bootstrapHash.isEmpty, !loggedIn, !authLoading, !bootstrapActive, !bootstrapAttempted else { return }
        bootstrapAttempted = true
        bootstrapActive = true
        bootstrapStarting = true
        bootstrapStage = .configuration
        defer {
            bootstrapStarting = false
            bootstrapStage = nil
        }
        var stage = "Не удалось получить настройки временного VPN"
        do {
            let config = try await api.bootstrapConfig(hash: bootstrapHash) { [weak self] attempt in
                self?.logConnection("Временный VPN: запрос настроек, попытка \(attempt)")
            }
            let duration = 120
            stage = "Не удалось запустить временный VPN"
            bootstrapStage = .tunnel
            logConnection("Запуск временного VPN")
            try await vpn.connect(makeTunnel(config, bootstrapDuration: duration))
            let deadline = Date().addingTimeInterval(TimeInterval(duration))
            stage = "Временный VPN не передаёт данные"
            bootstrapStage = .data
            try await api.checkTunnelGateway()
            guard vpn.state == .connected else { throw APIError.network }
            bootstrapDeadline = deadline
            logConnection("Временный VPN готов: шлюз ответил")
        } catch {
            await vpn.disconnect()
            bootstrapActive = false
            let message = "\(stage). \(error.localizedDescription)"
            authError = message
            logConnection(message)
        }
    }

    private func stopBootstrap() async {
        guard bootstrapActive else { return }
        bootstrapStarting = true
        await vpn.disconnect()
        bootstrapDeadline = nil
        bootstrapActive = false
        bootstrapStarting = false
    }

    func toggleAppearance() {
        darkMode.toggle()
        LocalStore.appearanceDark = darkMode
    }

    func loadInitialData() async {
        if api.isLoggedIn, !authLoading, !profileLoading {
            profileLoading = true
            authLoading = true
            authLoadingTitle = "Загрузка аккаунта…"
            do { try await loadAccount() }
            catch { authError = "Не удалось загрузить аккаунт. \(error.localizedDescription)" }
            profileLoading = false
            authLoading = false
        }
        if !loggedIn { await startBootstrap() }
        await loadAppearanceAndServers()
    }

    private func loadAccount() async throws {
        authLoadingTitle = "Загрузка аккаунта…"
        let loaded = try await api.getProfile()
        await stopBootstrap()
        profile = loaded
        loggedIn = true
    }

    private func loadAppearanceAndServers() async {
        theme = (try? await api.getTheme()) ?? theme
        if loggedIn { await refreshServers() }
    }

    func login(email: String, password: String, remember: Bool) async {
        guard !authLoading, !bootstrapStarting else { return }
        authLoading = true
        authLoadingTitle = "Вход…"
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
            try await loadAccount()
            Task { await loadAppearanceAndServers() }
        } catch {
            authError = error.localizedDescription
            logConnection("Вход не завершён")
        }
    }

    func register(email: String, password: String, code: String, remember: Bool) async {
        guard !authLoading, !bootstrapStarting else { return }
        authLoading = true
        authLoadingTitle = "Создание аккаунта…"
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
                try await loadAccount()
                Task { await loadAppearanceAndServers() }
            } else {
                regNeedMail = true
            }
        } catch {
            authError = error.localizedDescription
        }
    }

    func forgot(email: String) async {
        guard !authLoading, !bootstrapStarting else { return }
        authLoading = true
        authLoadingTitle = "Отправка…"
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
        sessionsVersion += 1
        Task {
            if vpnState == .connected || vpnState == .connecting {
                await vpn.disconnect()
            }
            await api.logoutSession()
            bootstrapAttempted = false
            profile = nil
            loggedIn = false
            vpnState = .disconnected
            connectedAt = nil
            menuOpen = false
            menuPage = .root
            payment = .idle
            await startBootstrap()
        }
    }

    func toggleVPN() async {
        guard !vpnActionInProgress else { return }
        vpnActionInProgress = true
        defer {
            vpnActionInProgress = false
            connectionStage = nil
        }
        errorMessage = nil
        if vpnState == .connected || vpnState == .connecting {
            vpnState = .disconnecting
            logConnection("Отключение VPN")
            await vpn.disconnect()
            vpnState = vpn.state
            connectedAt = nil
            try? await api.disconnect()
            if vpnState == .disconnected { logConnection("VPN отключён") }
            return
        }
        guard hasAccess else {
            menuOpen = false
            menuPage = .subscription
            return
        }
        vpnState = .connecting
        connectionStage = .configuration
        logConnection("Запрос настроек VPN")
        var sessionStarted = false
        var stage = "Не удалось получить настройки VPN"
        do {
            let cfg = try await api.registerDevice(name: UIDevice.current.name, preferredServer: selectedServer)
            connectionStage = .session
            stage = "Сервер не подтвердил подключение VPN"
            try await api.connect(preferredServer: cfg.selected_server ?? selectedServer)
            sessionStarted = true
            stage = "Не удалось запустить туннель"
            connectionStage = .tunnel
            logConnection("Ожидание ответа сервера VPN")
            let tunnel = makeTunnel(cfg)
            try await vpn.connect(tunnel)
            connectionStage = .data
            stage = "VPN не передаёт данные"
            logConnection("Проверка передачи данных через VPN")
            try await api.checkTunnelGateway()
            guard vpn.state == .connected else {
                throw APIError.server(vpn.readError() ?? "VPN отключился во время подключения")
            }
            vpnState = .connected
            connectedAt = Date()
            logConnection("VPN подключён: шлюз ответил")
            Task { await refreshSessions() }
        } catch {
            await vpn.disconnect()
            vpnState = vpn.state
            connectedAt = nil
            errorMessage = "\(stage). \(error.localizedDescription)"
            logConnection("\(stage). \(error.localizedDescription)")
            if sessionStarted { try? await api.disconnect() }
        }
    }

    private func makeTunnel(_ cfg: VpnConfig, bootstrapDuration: Int? = nil) -> TunnelConfig {
        let dns: [String]
        if dnsPreset == "custom", let custom = DnsInput.sanitize(customDns) {
            dns = custom
        } else {
            dns = cfg.wg_dns.split { $0 == "," || $0 == " " }.map { String($0) }.filter { !$0.isEmpty }
        }
        let workers = max(9, min(cfg.stream_count, 27))
        return TunnelConfig(
            deviceId: bootstrapDuration == nil ? cfg.device_id : "boot:\(api.deviceFingerprint)",
            serverIP: cfg.server_ip,
            serverPort: cfg.server_port,
            password: cfg.wdtt_password,
            hashes: cfg.vk_hashes,
            workers: workers,
            address: cfg.wg_address,
            dns: dns,
            mtu: ServerCatalog.mtu(slot: cfg.selected_server ?? selectedServer, ip: cfg.server_ip, recommended: cfg.wg_mtu),
            excludeCIDRs: bootstrapDuration == nil ? siteRules : [],
            sitesWhitelist: bootstrapDuration == nil && sitesWhitelist,
            russian: bootstrapDuration == nil ? RussianServices.policy(enabled: russianDirect) : nil,
            bootstrapDuration: bootstrapDuration
        )
    }

    func loadPlans() async {
        plans = (try? await api.getPlans()) ?? plans
        let version = sessionsVersion
        let account = profile?.id
        if api.isLoggedIn, let fresh = try? await api.getProfile(), version == sessionsVersion,
           api.isLoggedIn, account == nil || fresh.id == account {
            profile = fresh
        }
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
        let version = sessionsVersion
        let account = profile?.id
        let code = promoCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else { return }
        do {
            let res = try await api.checkPromo(code: code, plan: tier == 5 ? "monthly_5" : "monthly")
            guard version == sessionsVersion, api.isLoggedIn else { return }
            profile?.payment_previews = [:]
            if let fresh = try? await api.getProfile(), version == sessionsVersion,
               api.isLoggedIn, account == nil || fresh.id == account {
                profile = fresh
            }
            guard version == sessionsVersion, api.isLoggedIn else { return }
            var text = "Скидка \(Int(res.discount_percent))%"
            if res.extra_days > 0 { text += ", +\(res.extra_days) дн." }
            text += " · \(ShopPlan.currencyLabel(res.discounted_price)) вместо \(ShopPlan.currencyLabel(res.original_price))"
            promoMsg = text
        } catch {
            if version == sessionsVersion { promoMsg = error.localizedDescription }
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

    func refreshSessions() async {
        guard loggedIn, !sessionsFetching, !sessionsMutation else { return }
        sessionsFetching = true
        let version = sessionsVersion
        defer { sessionsFetching = false }
        do {
            let fresh = try await api.getProfile()
            guard !Task.isCancelled, loggedIn, version == sessionsVersion else { return }
            profile = fresh
            sessionsError = ""
        } catch {
            if !Task.isCancelled, loggedIn, version == sessionsVersion {
                sessionsError = "Не удалось обновить сессии. Показаны последние данные."
            }
        }
    }

    func renameDevice(_ id: String, _ name: String) async -> String? {
        guard !sessionsMutation else { return "Дождитесь завершения операции" }
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 64 else { return "Введите имя до 64 символов" }
        sessionsMutation = true
        sessionsVersion += 1
        let version = sessionsVersion
        defer { sessionsMutation = false }
        do {
            try await api.renameDevice(id: id, name: trimmed)
            guard loggedIn, version == sessionsVersion else { return nil }
            sessionsVersion += 1
            if var current = profile {
                current.devices = current.devices.map { device in
                    var updated = device
                    if updated.id == id { updated.device_name = trimmed }
                    return updated
                }
                profile = current
            }
            sessionsMutation = false
            await refreshSessions()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func deleteDevice(_ id: String) async -> String? {
        guard !sessionsMutation else { return "Дождитесь завершения операции" }
        sessionsMutation = true
        sessionsVersion += 1
        let version = sessionsVersion
        defer { sessionsMutation = false }
        do {
            try await api.deleteDevice(id: id)
            guard loggedIn, version == sessionsVersion else { return nil }
            if id == sessionDeviceId { logout(); return nil }
            sessionsVersion += 1
            if var current = profile {
                current.devices.removeAll { $0.id == id }
                current.devices_count = current.devices.count
                current.connected_count = current.devices.filter { $0.is_connected }.count
                profile = current
            }
            sessionsMutation = false
            await refreshSessions()
            return nil
        } catch {
            return error.localizedDescription
        }
    }
}

enum ConnectionStage: Double {
    case configuration = 0.18, session = 0.40, tunnel = 0.65, data = 0.90

    var title: String {
        switch self {
        case .configuration: return "Получение конфигурации…"
        case .session: return "Подготовка сессии…"
        case .tunnel: return "Подключение к серверу…"
        case .data: return "Проверка передачи данных…"
        }
    }
}
