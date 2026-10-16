import Foundation

// MARK: - API Service

class APIService: ObservableObject {
    static let shared = APIService()
    private let defaults = UserDefaults.standard

    var serverURL: String {
        get {
            let raw = (defaults.string(forKey: "server_url") ?? "")
                .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            let fixed = PublicApiFailover.rewriteStoredBase(raw)
            if fixed != raw { defaults.set(fixed, forKey: "server_url") }
            return fixed
        }
        set { defaults.set(PublicApiFailover.rewriteStoredBase(newValue), forKey: "server_url") }
    }
    var accessToken: String? {
        get { KeychainHelper.get("access_token") }
        set { if let v = newValue { KeychainHelper.set(v, key: "access_token") } else { KeychainHelper.delete("access_token") } }
    }
    var refreshToken: String? {
        get { KeychainHelper.get("refresh_token") }
        set { if let v = newValue { KeychainHelper.set(v, key: "refresh_token") } else { KeychainHelper.delete("refresh_token") } }
    }
    var isLoggedIn: Bool { accessToken != nil }
    var deviceFingerprint: String {
        if let fp = defaults.string(forKey: "device_fp") { return fp }
        let fp = UUID().uuidString
        defaults.set(fp, forKey: "device_fp")
        return fp
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        body: Encodable? = nil,
        auth: Bool = true
    ) async throws -> T {
        let data = try await requestData(path, method: method, body: body, auth: auth)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func requestData(
        _ path: String,
        method: String = "GET",
        body: Encodable? = nil,
        auth: Bool = true,
        allowRefresh: Bool = true
    ) async throws -> Data {
        let bases = PublicApiFailover.bases(preferred: serverURL)
        guard !bases.isEmpty else { throw APIError.noServer }
        var lastError: Error = APIError.network
        for base in bases {
            do {
                return try await requestOnce(path, method: method, body: body, auth: auth, base: base, allowRefresh: allowRefresh)
            } catch let e as APIError {
                switch e {
                case .network, .invalidURL:
                    lastError = e
                    continue
                default:
                    throw e
                }
            } catch {
                lastError = error
                continue
            }
        }
        throw lastError
    }

    private func requestOnce(
        _ path: String,
        method: String,
        body: Encodable?,
        auth: Bool,
        base: String,
        allowRefresh: Bool
    ) async throws -> Data {
        let trimmed = path.hasPrefix("/") ? String(path.dropFirst()) : path
        guard let url = URL(string: "\(base)/\(trimmed)") else { throw APIError.invalidURL }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.timeoutInterval = PublicApiFailover.timeoutSeconds(base)
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let token = accessToken {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body { req.httpBody = try JSONEncoder().encode(AnyEncodable(body)) }

        let cfg = URLSessionConfiguration.ephemeral
        cfg.timeoutIntervalForRequest = PublicApiFailover.timeoutSeconds(base)
        cfg.timeoutIntervalForResource = PublicApiFailover.timeoutSeconds(base) + 2
        let session = URLSession(configuration: cfg, delegate: TrustAllDelegate(), delegateQueue: nil)
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.network
        }

        guard let httpResp = response as? HTTPURLResponse else { throw APIError.network }
        if httpResp.statusCode == 401 && auth && allowRefresh {
            try await refreshTokens()
            return try await requestOnce(path, method: method, body: body, auth: auth, base: base, allowRefresh: false)
        }
        if PublicApiFailover.shouldTryNextBase(httpCode: httpResp.statusCode) {
            throw APIError.network
        }
        guard (200..<300).contains(httpResp.statusCode) else {
            let detail = serverDetail(data) ?? "Ошибка \(httpResp.statusCode)"
            throw APIError.server(detail)
        }
        return data
    }

    private func serverDetail(_ data: Data) -> String? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let s = obj["detail"] as? String { return s }
        if let list = obj["detail"] as? [[String: Any]] {
            let msgs = list.compactMap { $0["msg"] as? String }
            if !msgs.isEmpty { return msgs.joined(separator: " ") }
        }
        return nil
    }

    private func refreshTokens() async throws {
        guard let rt = refreshToken else { throw APIError.unauthorized }
        struct RefReq: Encodable { let refresh_token: String }
        let data = try await requestData("api/auth/refresh", method: "POST", body: RefReq(refresh_token: rt), auth: false, allowRefresh: false)
        let resp = try JSONDecoder().decode(TokenResponse.self, from: data)
        accessToken = resp.access_token
        refreshToken = resp.refresh_token
    }

    // ─── API Methods ─────────────────────────────────────────────────────────

    func login(email: String, password: String) async throws -> TokenResponse {
        let resp: TokenResponse = try await request("api/auth/login", method: "POST", body: LoginRequest(email: email, password: password), auth: false)
        accessToken = resp.access_token
        refreshToken = resp.refresh_token
        return resp
    }

    /// true — сразу вошли. false — нужно подтвердить почту.
    func register(email: String, password: String, referralOrPromo: String?) async throws -> Bool {
        let code = referralOrPromo?.trimmingCharacters(in: .whitespacesAndNewlines)
        let data = try await requestData(
            "api/auth/register",
            method: "POST",
            body: RegisterRequest(email: email, password: password, referral_or_promo: (code?.isEmpty == false) ? code : nil),
            auth: false
        )
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        let flag: String? = {
            if let s = obj?["email_confirmation_required"] as? String { return s }
            if let b = obj?["email_confirmation_required"] as? Bool { return b ? "true" : "false" }
            return nil
        }()
        let themeSkip = (try? await getTheme())?.skip_email_confirmation == true
        if EmailConfirmationPolicy.skipConfirmation(themeSkip: themeSkip, requiredFlag: flag) {
            _ = try await login(email: email, password: password)
            return true
        }
        return false
    }

    func forgotPassword(email: String) async throws {
        struct Req: Encodable { let email: String }
        _ = try await requestData("api/auth/forgot-password", method: "POST", body: Req(email: email), auth: false)
    }

    func getProfile() async throws -> UserProfile {
        try await request("api/users/me")
    }

    func getTheme() async throws -> ThemeData {
        let data = try await requestData("api/vpn/theme", auth: false)
        defaults.set(data, forKey: "cached_theme_json")
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        let theme = ThemeData(dict: obj)
        let extra = theme.hive_standby_api_urls
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        PublicApiFailover.extraBases = extra
        return theme
    }

    func cachedTheme() -> ThemeData? {
        guard let data = defaults.data(forKey: "cached_theme_json"),
              let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return ThemeData(dict: obj)
    }

    func getPlans() async throws -> [ShopPlan] {
        try await request("api/payments/plans?all=1", auth: false)
    }

    func registerDevice(name: String, preferredServer: String) async throws -> VpnConfig {
        struct Req: Encodable {
            let device_name: String
            let device_type: String
            let device_fingerprint: String
            let wg_public_key: String?
            let preferred_server: String
        }
        return try await request(
            "api/vpn/device/register",
            method: "POST",
            body: Req(
                device_name: name,
                device_type: "ios",
                device_fingerprint: deviceFingerprint,
                wg_public_key: nil,
                preferred_server: preferredServer
            )
        )
    }

    func connect(preferredServer: String) async throws {
        struct Req: Encodable {
            let device_fingerprint: String
            let device_type: String
            let preferred_server: String
        }
        _ = try await requestData(
            "api/vpn/connect",
            method: "POST",
            body: Req(device_fingerprint: deviceFingerprint, device_type: "ios", preferred_server: preferredServer)
        )
    }

    func disconnect() async throws {
        struct Req: Encodable { let device_fingerprint: String }
        _ = try await requestData("api/vpn/disconnect", method: "POST", body: Req(device_fingerprint: deviceFingerprint))
    }

    func logoutSession() async {
        struct Req: Encodable { let device_fingerprint: String }
        _ = try? await requestData("api/users/logout", method: "POST", body: Req(device_fingerprint: deviceFingerprint))
        accessToken = nil
        refreshToken = nil
    }

    func initPayment(plan: String, promo: String? = nil) async throws -> PaymentResponse {
        struct Req: Encodable { let plan_type: String; let promo_code: String? }
        return try await request("api/payments/init", method: "POST", body: Req(plan_type: plan, promo_code: promo))
    }

    func previewPayment(plan: String) async throws -> PaymentPreview {
        struct Req: Encodable { let plan_type: String }
        return try await request("api/payments/preview", method: "POST", body: Req(plan_type: plan))
    }

    func paymentStatus(label: String) async throws -> PaymentStatus {
        let safe = label.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? label
        return try await request("api/payments/status/\(safe)")
    }

    func referral() async throws -> ReferralInfo {
        try await request("api/users/me/referral")
    }

    func checkPromo(code: String, plan: String) async throws -> PromoCheck {
        struct Req: Encodable { let code: String; let plan_type: String }
        return try await request("api/payments/promo/check", method: "POST", body: Req(code: code, plan_type: plan))
    }

    func fetchServers() async throws -> VpnServersBody {
        try await request("api/vpn/servers")
    }

    func selectServer(_ slot: String) async throws -> VpnServersBody {
        struct Req: Encodable {
            let device_fingerprint: String
            let preferred_server: String
            let app_version: String
        }
        return try await request(
            "api/vpn/servers/select",
            method: "POST",
            body: Req(device_fingerprint: deviceFingerprint, preferred_server: slot, app_version: "1.0.0")
        )
    }

    func renameDevice(id: String, name: String) async throws {
        struct Req: Encodable { let device_name: String }
        _ = try await requestData("api/users/devices/\(id)", method: "PATCH", body: Req(device_name: name))
    }

    func deleteDevice(id: String) async throws {
        _ = try await requestData("api/users/devices/\(id)", method: "DELETE")
    }

    func logout() { accessToken = nil; refreshToken = nil }
}

// MARK: - Errors

enum APIError: LocalizedError {
    case noServer, invalidURL, network, unauthorized
    case server(String)
    var errorDescription: String? {
        switch self {
        case .noServer: return "Сервер не настроен"
        case .invalidURL: return "Неверный URL"
        case .network: return "Ошибка сети"
        case .unauthorized: return "Необходима авторизация"
        case .server(let msg): return msg
        }
    }
}

// MARK: - Helpers

struct AnyEncodable: Encodable {
    private let _encode: (Encoder) throws -> Void
    init(_ value: Encodable) { _encode = value.encode }
    func encode(to encoder: Encoder) throws { try _encode(encoder) }
}

class TrustAllDelegate: NSObject, URLSessionDelegate {
    func urlSession(_ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
                    completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
        completionHandler(.useCredential, URLCredential(trust: challenge.protectionSpace.serverTrust!))
    }
}

struct KeychainHelper {
    static func set(_ value: String, key: String) {
        let data = value.data(using: .utf8)!
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key, kSecValueData as String: data]
        SecItemDelete(query as CFDictionary)
        SecItemAdd(query as CFDictionary, nil)
    }
    static func get(_ key: String) -> String? {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key, kSecReturnData as String: true, kSecMatchLimit as String: kSecMatchLimitOne]
        var result: AnyObject?
        SecItemCopyMatching(query as CFDictionary, &result)
        return (result as? Data).flatMap { String(data: $0, encoding: .utf8) }
    }
    static func delete(_ key: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key]
        SecItemDelete(query as CFDictionary)
    }
}
