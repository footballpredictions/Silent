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
    @Published private(set) var launchStage: ConnectionStage? = .configuration
    @Published var authLoading = false
    @Published var authLoadingTitle = "Вход…"
    @Published var authError: String?
    @Published var bootstrapDeadline: Date?
    @Published var bootstrapStarting = false
    @Published private(set) var bootstrapFailed = false
    @Published private(set) var connectionLog: [VPNLogEntry] = []
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
    @Published private(set) var selectingServer = false

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
    private var bootstrapCell = 0
    private var vpnActionInProgress = false
    private var connectedAt: Date?
    private var canRecoverTunnel = false
    private var tunnelRecovery: Task<Void, Never>?
    private var profileLoading = false
    private var serverSelectionVersion = 0

    private let bootstrapHash = BootstrapLaunch.callHash(Bundle.main.object(forInfoDictionaryKey: "SilentBootstrapVKHash") as? String ?? "") ?? ""
    private let bootstrapPassword: String = {
        guard let encoded = Bundle.main.object(forInfoDictionaryKey: "SilentBootstrapTransport") as? String,
              let bytes = Data(base64Encoded: encoded), let password = String(data: bytes, encoding: .utf8) else { return "" }
        return password
    }()
    private let bootstrapCacheKey = "ios-vpn-bootstrap-config"

    var palette: Palette { Palette.resolve(theme: theme, dark: darkMode) }
    var hasAccess: Bool { profile?.is_admin == true || profile?.subscription.is_active == true }
    var sessionDeviceId: String? {
        guard let profile else { return nil }
        if let id = UserDefaults.standard.string(forKey: "vpn-session-\(profile.id)"),
           profile.devices.contains(where: { $0.id == id }) { return id }
        guard let config = AppIdentity.readTunnelConfig(), config.bootstrapDuration == nil,
              profile.devices.contains(where: { $0.id == config.deviceId }) else { return nil }
        return config.deviceId
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
            launchStage = .complete
            try? await Task.sleep(nanoseconds: 260_000_000)
            launchStage = nil
            await loadAppearanceAndServers()
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
        if state == .connected, connectedAt == nil {
            connectedAt = Date()
            canRecoverTunnel = true
        }
        if state == .disconnected, wasActive {
            let uptime = connectedAt.map { max(0, Int(Date().timeIntervalSince($0))) }
            connectedAt = nil
            let reason = vpn.readError() ?? "Соединение VPN завершено"
            let duration = uptime.map { " · \($0) с" } ?? ""
            errorMessage = reason
            logConnection(reason + duration, level: .error)
            let shouldRecover = canRecoverTunnel && loggedIn
            canRecoverTunnel = false
            tunnelRecovery?.cancel()
            tunnelRecovery = Task { [weak self] in
                await self?.recoverAfterDisconnect(allowed: shouldRecover)
            }
        }
    }

    private func recoverAfterDisconnect(allowed: Bool) async {
        guard let error = await vpn.lastDisconnectError(), !Task.isCancelled, vpnState == .disconnected else { return }
        logConnection("iOS: \(error.domain) / \(error.code)", level: .error)
        guard allowed, error.domain == "NEVPNConnectionErrorDomain", error.code == 12,
              hasAccess, let config = AppIdentity.readTunnelConfig(), config.bootstrapDuration == nil,
              config.deviceId == sessionDeviceId else { return }
        do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
        guard !Task.isCancelled, vpnState == .disconnected, loggedIn, !vpnActionInProgress else { return }
        vpnActionInProgress = true
        defer { vpnActionInProgress = false; tunnelRecovery = nil }
        vpnState = .connecting
        logConnection("iOS остановила расширение. Восстановление VPN")
        do {
            try await vpn.connect(config)
            try await api.checkTunnelGateway()
            guard vpn.state == .connected else { throw APIError.network }
            vpnState = .connected
            connectedAt = Date()
            errorMessage = nil
            logConnection("Соединение восстановлено", level: .success)
        } catch {
            await vpn.disconnect()
            vpnState = vpn.state
            if !Task.isCancelled {
                errorMessage = "Не удалось восстановить VPN. Подключитесь снова."
                logConnection(errorMessage ?? "Ошибка восстановления", level: .error)
            }
        }
    }

    private func logConnection(_ text: String, level: VPNLogLevel = .info) {
        connectionLog.append(VPNLogEntry(date: Date(), level: level, source: "Приложение", message: text))
        if connectionLog.count > 200 { connectionLog.removeFirst() }
    }

    func clearVPNLog() {
        connectionLog.removeAll()
        VPNLog.clear()
    }

    private func startBootstrap() async {
        guard !bootstrapHash.isEmpty, !loggedIn, !authLoading, !bootstrapActive, !bootstrapAttempted else { return }
        bootstrapAttempted = true
        bootstrapActive = true
        bootstrapStarting = true
        bootstrapFailed = false
        if launchStage != nil { launchStage = .configuration }
        defer { bootstrapStarting = false }
        var stage = "Не удалось получить настройки временного VPN"
        do {
            if let local = BootstrapLaunch.configuration(hash: bootstrapHash, fingerprint: api.deviceFingerprint,
                                                         password: bootstrapPassword, cell: bootstrapCell) {
                logConnection("Временный VPN: запуск через Соту \(bootstrapCell + 1) без запроса HTTPS")
                stage = "Не удалось запустить временный VPN"
                do {
                    try await connectBootstrap(local)
                    return
                } catch {
                    await vpn.disconnect()
                    try Task.checkCancellation()
                    guard vpn.state == .disconnected else { throw error }
                    logConnection("Временный VPN: сота не подтвердила подключение. Пробуем получить настройки через HTTPS", level: .error)
                }
            }

            stage = "Не удалось получить настройки временного VPN"
            let config: TunnelConfig
            do {
                let fresh = try await api.bootstrapConfig(hash: bootstrapHash) { [weak self] message in
                    self?.logConnection("Временный VPN: \(message)")
                }
                config = makeTunnel(fresh, bootstrapDuration: BootstrapLaunch.duration)
            } catch APIError.bootstrapUnavailable(let message) {
                guard let value = KeychainHelper.get(bootstrapCacheKey), let data = Data(base64Encoded: value),
                      let saved = try? JSONDecoder().decode(BootstrapCache.self, from: data),
                      saved.config.deviceId == "boot:\(api.deviceFingerprint)",
                      saved.config.hashes.contains(bootstrapHash),
                      saved.savedAt > Date().addingTimeInterval(-86_400) else {
                    throw APIError.server(message)
                }
                logConnection("Сервер конфигурации недоступен. Используем сохранённые настройки временного VPN")
                config = saved.config
            }
            stage = "Не удалось запустить временный VPN"
            try await connectBootstrap(config)
        } catch {
            await vpn.disconnect()
            bootstrapActive = false
            bootstrapFailed = true
            let message = "\(stage). \(error.localizedDescription)"
            authError = message
            logConnection(message, level: .error)
        }
    }

    private func connectBootstrap(_ config: TunnelConfig) async throws {
        if launchStage != nil { launchStage = .tunnel }
        try await vpn.connect(config)
        let deadline = Date().addingTimeInterval(TimeInterval(BootstrapLaunch.duration))
        if launchStage != nil { launchStage = .data }
        try await api.checkTunnelGateway()
        guard vpn.state == .connected else { throw APIError.network }
        bootstrapDeadline = deadline
        if let data = try? JSONEncoder().encode(BootstrapCache(savedAt: Date(), config: config)) {
            KeychainHelper.set(data.base64EncodedString(), key: bootstrapCacheKey)
        }
        logConnection("Временный VPN готов: шлюз ответил", level: .success)
    }

    private func stopBootstrap() async {
        guard bootstrapActive else { return }
        bootstrapStarting = true
        await vpn.disconnect()
        bootstrapDeadline = nil
        bootstrapActive = false
        bootstrapStarting = false
    }

    func retryBootstrap() async {
        guard !authLoading, !bootstrapStarting, !bootstrapActive, !loggedIn else { return }
        bootstrapAttempted = false
        bootstrapCell = (bootstrapCell + 1) % BootstrapLaunch.cellHosts.count
        authError = nil
        await startBootstrap()
    }

    func toggleAppearance() {
        darkMode.toggle()
        LocalStore.appearanceDark = darkMode
    }

    private func loadInitialData() async {
        if api.isLoggedIn, !authLoading, !profileLoading {
            profileLoading = true
            authLoading = true
            authLoadingTitle = "Загрузка аккаунта…"
            launchStage = .session
            do { try await loadAccount() }
            catch { authError = "Не удалось загрузить аккаунт. \(error.localizedDescription)" }
            profileLoading = false
            authLoading = false
        }
        if !loggedIn {
            await startBootstrap()
            if api.isLoggedIn, bootstrapDeadline != nil {
                launchStage = .session
                do {
                    try await loadAccount()
                    authError = nil
                } catch {
                    authError = "Не удалось восстановить аккаунт. \(error.localizedDescription)"
                }
            }
        }
    }

    private func loadAccount() async throws {
        authLoadingTitle = "Загрузка аккаунта…"
        let loaded = try await api.getProfile()
        await stopBootstrap()
        profile = loaded
        loggedIn = true
        bootstrapFailed = false
    }

    private func rememberLoginSession() {
        guard let profile else { return }
        let devices = profile.devices.filter { $0.device_type.lowercased() == "ios" }
        if devices.count == 1, let device = devices.first {
            UserDefaults.standard.set(device.id, forKey: "vpn-session-\(profile.id)")
        }
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
            rememberLoginSession()
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
                rememberLoginSession()
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
        tunnelRecovery?.cancel()
        canRecoverTunnel = false
        sessionsVersion += 1
        serverSelectionVersion += 1
        Task {
            if vpnState == .connected || vpnState == .connecting {
                await vpn.disconnect()
            }
            await api.logoutSession()
            bootstrapAttempted = false
            profile = nil
            loggedIn = false
            servers = []
            serverHint = ""
            vpnState = .disconnected
            connectedAt = nil
            menuOpen = false
            menuPage = .root
            payment = .idle
            await startBootstrap()
        }
    }

    func toggleVPN() async {
        guard !vpnActionInProgress, !selectingServer else { return }
        tunnelRecovery?.cancel()
        vpnActionInProgress = true
        defer { vpnActionInProgress = false }
        errorMessage = nil
        if vpnState == .connected || vpnState == .connecting {
            vpnState = .disconnecting
            logConnection("Отключение VPN")
            await vpn.disconnect()
            vpnState = vpn.state
            connectedAt = nil
            canRecoverTunnel = false
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
        logConnection("Запрос настроек VPN")
        var sessionStarted = false
        var stage = "Сервер не подтвердил подключение VPN"
        do {
            let preferred = selectedServer
            do {
                try await api.connect(preferredServer: preferred)
            } catch APIError.http(404, _) {
                _ = try await api.registerDevice(name: UIDevice.current.name, preferredServer: preferred)
                try await api.connect(preferredServer: preferred)
            }
            sessionStarted = true
            stage = "Не удалось получить настройки VPN"
            // connect provisions missing per-account relay hashes; reading the
            // config first could leave this attempt using stale bootstrap hashes.
            let cfg = try await api.vpnConfig(preferredServer: preferred)
            if let profile { UserDefaults.standard.set(cfg.device_id, forKey: "vpn-session-\(profile.id)") }
            logConnection("Конфигурация получена. Подготовка сессии")
            if let confirmed = cfg.selected_server?.lowercased(), confirmed != selectedServer,
               ServerCatalog.slots.contains(where: { $0.key == confirmed }) {
                serverSelectionVersion += 1
                selectedServer = confirmed
                LocalStore.preferredServer = confirmed
            }
            stage = "Не удалось запустить туннель"
            logConnection("Ожидание ответа сервера VPN")
            let tunnel = makeTunnel(cfg)
            try await vpn.connect(tunnel)
            stage = "VPN не передаёт данные"
            logConnection("Проверка передачи данных через VPN")
            try await api.checkTunnelGateway()
            guard vpn.state == .connected else {
                throw APIError.server(vpn.readError() ?? "VPN отключился во время подключения")
            }
            vpnState = .connected
            connectedAt = Date()
            canRecoverTunnel = true
            logConnection("VPN подключён: шлюз ответил", level: .success)
            Task { await refreshSessions() }
        } catch {
            await vpn.disconnect()
            vpnState = vpn.state
            connectedAt = nil
            errorMessage = "\(stage). \(error.localizedDescription)"
            logConnection("\(stage). \(error.localizedDescription)", level: .error)
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
        guard loggedIn, !selectingServer else { return }
        let version = serverSelectionVersion
        let account = profile?.id
        do {
            let body = try await api.fetchServers()
            guard !Task.isCancelled, loggedIn, profile?.id == account, version == serverSelectionVersion else { return }
            applyServers(body)
            serverHint = ""
        } catch {
            guard !Task.isCancelled, loggedIn, profile?.id == account, version == serverSelectionVersion, servers.isEmpty else { return }
            serverHint = "Не удалось загрузить список серверов. Попробуйте ещё раз."
        }
    }

    func selectServer(_ key: String) async {
        guard loggedIn, !selectingServer, key != selectedServer, servers.contains(where: { $0.key == key }) else { return }
        guard vpnState == .disconnected, !vpnActionInProgress else {
            serverHint = "Отключите VPN перед сменой сервера."
            return
        }
        serverSelectionVersion += 1
        selectingServer = true
        serverHint = ""
        let account = profile?.id
        defer { selectingServer = false }
        do {
            let body = try await api.selectServer(key)
            guard loggedIn, profile?.id == account else { return }
            applyServers(body)
            serverHint = selectedServer == key ? "Сервер выбран" : "Сервер предложил другой доступный вариант"
        } catch {
            guard loggedIn, profile?.id == account else { return }
            serverHint = error.localizedDescription
        }
    }

    private func applyServers(_ body: VpnServersBody) {
        var seen = Set<String>()
        servers = body.servers.compactMap { item in
            let key = item.key.lowercased()
            guard let slot = ServerCatalog.slots.first(where: { $0.key == key }), seen.insert(key).inserted else { return nil }
            let title = (item.title.isEmpty || (key == "server4" && item.title == "Сервер 4")) ? slot.title : item.title
            return VpnServer(key: key, title: title)
        }
        if let selected = body.selected_server?.lowercased(), servers.contains(where: { $0.key == selected }) {
            selectedServer = selected
            LocalStore.preferredServer = selected
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

private struct BootstrapCache: Codable {
    let savedAt: Date
    let config: TunnelConfig
}

enum ConnectionStage: Double {
    case configuration = 0.18, session = 0.40, tunnel = 0.65, data = 0.90, complete = 1

    var title: String {
        switch self {
        case .configuration: return "Получение конфигурации…"
        case .session: return "Подготовка сессии…"
        case .tunnel: return "Подключение к серверу…"
        case .data: return "Проверка передачи данных…"
        case .complete: return "Готово"
        }
    }
}
