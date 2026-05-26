import Foundation

// MARK: - Models

struct LoginRequest: Encodable { let email: String; let password: String }
struct RegisterRequest: Encodable { let email: String; let password: String }
struct TokenResponse: Decodable { let access_token: String; let refresh_token: String }

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
    var app_name: String = "Silent"
    var support_url: String = ""
    var privacy_url: String = ""
    var terms_url: String = ""
}

struct PaymentResponse: Decodable {
    let url: String; let wallet: String; let label: String; let amount: Double
}

// MARK: - API Service

class APIService: ObservableObject {
    static let shared = APIService()
    private let defaults = UserDefaults.standard

    var serverURL: String {
        get { defaults.string(forKey: "server_url") ?? "" }
        set { defaults.set(newValue.trimmingCharacters(in: .init(charactersIn: "/")), forKey: "server_url") }
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
        guard !serverURL.isEmpty else { throw APIError.noServer }
        guard let url = URL(string: "\(serverURL)/\(path)") else { throw APIError.invalidURL }

        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if auth, let token = accessToken {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body { req.httpBody = try JSONEncoder().encode(AnyEncodable(body)) }

        let session = URLSession(configuration: .default, delegate: TrustAllDelegate(), delegateQueue: nil)
        let (data, response) = try await session.data(for: req)

        guard let httpResp = response as? HTTPURLResponse else { throw APIError.network }
        if httpResp.statusCode == 401 && auth {
            try await refreshTokens()
            return try await request(path, method: method, body: body, auth: auth)
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

    func login(email: String, password: String) async throws -> TokenResponse {
        let resp: TokenResponse = try await request("api/auth/login", method: "POST", body: LoginRequest(email: email, password: password), auth: false)
        accessToken = resp.access_token; refreshToken = resp.refresh_token
        return resp
    }

    func register(email: String, password: String) async throws {
        let _: [String: String] = try await request("api/auth/register", method: "POST", body: RegisterRequest(email: email, password: password), auth: false)
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

    var bootstrapHash: String? {
        get { defaults.string(forKey: "vk_bootstrap_hash") }
        set { defaults.set(newValue, forKey: "vk_bootstrap_hash") }
    }

    var preLoginFingerprint: String {
        if let fp = defaults.string(forKey: "pre_login_fp") { return fp }
        let fp = UUID().uuidString
        defaults.set(fp, forKey: "pre_login_fp")
        return fp
    }

    func fetchBootstrapConfig() async throws -> VpnConfig {
        guard let boot = bootstrapHash, !boot.isEmpty else {
            throw APIError.server("Bootstrap-хеш не найден. Привяжите VK.")
        }
        struct Req: Encodable {
            let bootstrap_hash: String
            let device_type: String
            let device_fingerprint: String
        }
        return try await request(
            "api/vpn/bootstrap-config",
            method: "POST",
            body: Req(bootstrap_hash: boot, device_type: "ios", device_fingerprint: preLoginFingerprint),
            auth: false
        )
    }

    func resolveVpnConfig(deviceName: String) async throws -> VpnConfig {
        do {
            return try await registerDevice(name: deviceName, type: "ios")
        } catch {
            if bootstrapHash != nil {
                return try await fetchBootstrapConfig()
            }
            throw error
        }
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
