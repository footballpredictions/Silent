import Foundation

// MARK: - Models

struct LoginRequest: Encodable { let email: String; let password: String }
struct RegisterRequest: Encodable { let email: String; let password: String }
struct TokenResponse: Decodable { let access_token: String; let refresh_token: String }
struct EmptyBody: Encodable {}
struct QrStartResponse: Decodable { let token: String; let expires_in: Int; let payload: String }
struct QrPollResponse: Decodable {
    let status: String
    let access_token: String?
    let refresh_token: String?
}
struct QrUserCodeResponse: Decodable { let code: String; let expires_in: Int; let payload: String }

struct SubscriptionInfo: Decodable {
    let is_active: Bool
    let plan_type: String?
    let expires_at: String?
    let days_left: Int
}

struct DeviceInfo: Decodable, Identifiable {
    let id: String
    let device_name: String
    let device_type: String
    let is_connected: Bool
    let last_connected: String?
}

struct UserProfile: Decodable {
    let id: String
    let email: String
    let display_id: String
    let subscription: SubscriptionInfo
    let devices: [DeviceInfo]
    let devices_count: Int
    let max_devices: Int
}

struct VpnConfig: Decodable {
    let device_id: String
    let wg_private_key: String
    let wg_address: String
    let wg_dns: String
    let server_ip: String
    let server_port: Int
    let server_public_key: String
    let wdtt_password: String
    let vk_hashes: [String]
    let stream_count: Int
}

struct ThemeData: Decodable {
    var primary_color: String = "#000000"
    var background_color: String = "#FFFFFF"
    var text_color: String = "#000000"
    var accent_color: String = "#1A1A1A"
    var toggle_on_color: String = "#000000"
    var toggle_off_color: String = "#CCCCCC"
    var font_family: String = "Inter"
    var logo_url: String = ""
    var home_bg_image_url: String = ""
    var app_name: String = "Silent"
    var support_url: String = "https://t.me/silentvpn3?direct"
    var telegram_channel_url: String = "https://t.me/silentvpn3"
    var telegram_proxy_url: String = ""
    var telegram_proxy_menu_label: String = "Ускорить Telegram"
    var privacy_url: String = ""
    var terms_url: String = ""
    var login_qr_title: String?
    var login_qr_show_hint: String?
    var login_qr_confirm_label: String?
    var login_qr_confirm_hint: String?
    var menu_qr_label: String?
    var skip_email_confirmation: Bool?
    var subscription_tier_3_label: String?
    var subscription_tier_5_label: String?
    var subscription_choose_tier_title: String?
    var subscription_choose_plan_title: String?
}

struct PaymentResponse: Decodable {
    let url: String; let wallet: String; let label: String; let amount: Double
}

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
        let bases = PublicApiFailover.bases(preferred: serverURL)
        guard !bases.isEmpty else { throw APIError.noServer }
        var lastError: Error = APIError.network
        for base in bases {
            do {
                return try await requestOnce(path, method: method, body: body, auth: auth, base: base)
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

    private func requestOnce<T: Decodable>(
        _ path: String,
        method: String,
        body: Encodable?,
        auth: Bool,
        base: String
    ) async throws -> T {
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
        if httpResp.statusCode == 401 && auth {
            try await refreshTokens()
            return try await requestOnce(path, method: method, body: body, auth: auth, base: base)
        }
        if PublicApiFailover.shouldTryNextBase(httpCode: httpResp.statusCode) {
            throw APIError.network
        }
        guard (200..<300).contains(httpResp.statusCode) else {
            let detail = (try? JSONDecoder().decode([String: String].self, from: data))?["detail"] ?? "Error \(httpResp.statusCode)"
            throw APIError.server(detail)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func refreshTokens() async throws {
        guard let rt = refreshToken else { throw APIError.unauthorized }
        struct RefReq: Encodable { let refresh_token: String }
        let resp: TokenResponse = try await request("api/auth/refresh", method: "POST", body: RefReq(refresh_token: rt), auth: false)
        accessToken = resp.access_token
        refreshToken = resp.refresh_token
    }

    // ─── API Methods ─────────────────────────────────────────────────────────

    func qrStart() async throws -> QrStartResponse {
        try await request("api/auth/qr/start", method: "POST", body: EmptyBody(), auth: false)
    }

    func qrPoll(token: String) async throws -> QrPollResponse {
        try await request("api/auth/qr/poll?token=\(token)", auth: false)
    }

    func qrUserCode() async throws -> QrUserCodeResponse {
        try await request("api/auth/qr/user-code", method: "POST", body: EmptyBody())
    }

    func qrApprove(payload: String) async throws {
        struct Req: Encodable { let payload: String }
        let _: [String: Bool] = try await request("api/auth/qr/approve", method: "POST", body: Req(payload: payload))
    }

    func qrRedeem(payload: String) async throws -> TokenResponse {
        struct Req: Encodable { let payload: String }
        let resp: TokenResponse = try await request("api/auth/qr/redeem", method: "POST", body: Req(payload: payload), auth: false)
        accessToken = resp.access_token; refreshToken = resp.refresh_token
        return resp
    }

    func login(email: String, password: String) async throws -> TokenResponse {
        let resp: TokenResponse = try await request("api/auth/login", method: "POST", body: LoginRequest(email: email, password: password), auth: false)
        accessToken = resp.access_token; refreshToken = resp.refresh_token
        return resp
    }

    func register(email: String, password: String) async throws {
        let resp: [String: String] = try await request("api/auth/register", method: "POST", body: RegisterRequest(email: email, password: password), auth: false)
        if EmailConfirmationPolicy.skipConfirmation(
            themeSkip: (try? await getTheme())?.skip_email_confirmation == true,
            requiredFlag: resp["email_confirmation_required"]
        ) {
            _ = try await login(email: email, password: password)
        }
    }

    func getProfile() async throws -> UserProfile {
        try await request("api/users/me")
    }

    func getTheme() async throws -> ThemeData {
        try await request("api/vpn/theme", auth: false)
    }

    func registerDevice(name: String, type: String) async throws -> VpnConfig {
        struct Req: Encodable { let device_name: String; let device_type: String; let device_fingerprint: String; let wg_public_key: String? }
        return try await request("api/vpn/device/register", method: "POST", body: Req(device_name: name, device_type: type, device_fingerprint: deviceFingerprint, wg_public_key: nil))
    }

    func connect() async throws {
        struct Req: Encodable { let device_fingerprint: String; let device_type: String }
        let _: [String: String] = try await request("api/vpn/connect", method: "POST", body: Req(device_fingerprint: deviceFingerprint, device_type: "ios"))
    }

    func disconnect() async throws {
        struct Req: Encodable { let device_fingerprint: String }
        let _: [String: String] = try await request("api/vpn/disconnect", method: "POST", body: Req(device_fingerprint: deviceFingerprint))
    }

    func initPayment(plan: String, promo: String? = nil) async throws -> PaymentResponse {
        struct Req: Encodable { let plan_type: String; let promo_code: String? }
        return try await request("api/payments/init", method: "POST", body: Req(plan_type: plan, promo_code: promo))
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
