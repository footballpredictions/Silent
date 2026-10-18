import Foundation

struct LoginRequest: Encodable { let email: String; let password: String }
struct RegisterRequest: Encodable { let email: String; let password: String; let referral_or_promo: String? }
struct TokenResponse: Decodable { let access_token: String; let refresh_token: String }
struct EmptyBody: Encodable {}

struct SubscriptionInfo: Decodable {
    let is_active: Bool
    let plan_type: String?
    let expires_at: String?
    let days_left: Int
}

struct DeviceInfo: Decodable, Identifiable {
    let id: String
    var device_name: String
    let device_type: String
    let is_connected: Bool
    let last_connected: String?
}

struct UserProfile: Decodable {
    let id: String
    let email: String
    let display_id: String
    let is_admin: Bool
    let subscription: SubscriptionInfo
    var devices: [DeviceInfo]
    var devices_count: Int
    var connected_count: Int
    let max_devices: Int
    let payment_previews: [String: PaymentPreview]?

    private enum CodingKeys: String, CodingKey {
        case id, email, display_id, is_admin, subscription, devices, devices_count, connected_count, max_devices, payment_previews
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        email = try c.decode(String.self, forKey: .email)
        display_id = try c.decode(String.self, forKey: .display_id)
        is_admin = try c.decodeIfPresent(Bool.self, forKey: .is_admin) ?? false
        subscription = try c.decode(SubscriptionInfo.self, forKey: .subscription)
        devices = try c.decodeIfPresent([DeviceInfo].self, forKey: .devices) ?? []
        devices_count = try c.decodeIfPresent(Int.self, forKey: .devices_count) ?? devices.count
        connected_count = try c.decodeIfPresent(Int.self, forKey: .connected_count) ?? 0
        max_devices = try c.decodeIfPresent(Int.self, forKey: .max_devices) ?? 3
        payment_previews = try c.decodeIfPresent([String: PaymentPreview].self, forKey: .payment_previews)
    }

    var sessionsBadge: String {
        let limit = (is_admin || max_devices <= 0) ? "∞" : "\(max_devices)"
        return "\(devices_count)/\(limit)"
    }
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

struct ShopPlan: Decodable, Identifiable {
    let id: String
    let name: String
    let price: Double
    let days: Int
    let devices: Int

    var priceLabel: String {
        if price.rounded() == price { return "\(Int(price)) ₽" }
        return String(format: "%.0f ₽", price)
    }
}

struct PaymentResponse: Decodable {
    let url: String
    let wallet: String?
    let label: String
    let amount: Double?
}

struct PaymentPreview: Decodable {
    let amount: Double
    let expires_at: String
    let message: String
    let calculated_at: String?

    var isFresh: Bool {
        guard let stamp = calculated_at else { return false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: stamp)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: stamp)
        }
        guard let date else { return false }
        let age = Date().timeIntervalSince(date)
        return age >= 0 && age <= 300
    }
}

struct PaymentStatus: Decodable {
    let label: String
    let status: String
    let plan_type: String?
    let amount: Double?
    let subscription_applied: Bool?
}

struct ReferralInfo: Decodable {
    let referral_code: String
    let referral_link: String
    let invited_count: Int
    let rewarded_count: Int
    let pending_count: Int
    let bonus_days: Int
    let monthly_reward_limit: Int
    let rewarded_last_30_days: Int
}

struct PromoCheck: Decodable {
    let code: String
    let discount_percent: Double
    let extra_days: Int
    let original_price: Double
    let discounted_price: Double
}

struct VpnServer: Decodable, Identifiable {
    var id: String { key }
    let key: String
    let title: String
    let public_ip: String?
    let wdtt_port: Int?
    let online_count: Int?
}

struct VpnServersBody: Decodable {
    let selected_server: String?
    let servers: [VpnServer]
}

struct ThemeData {
    var primary_color = "#000000"
    var background_color = "#FFFFFF"
    var text_color = "#000000"
    var accent_color = "#1A1A1A"
    var toggle_on_color = "#000000"
    var toggle_off_color = "#CCCCCC"
    var font_family = "Inter"
    var logo_url = ""
    var home_bg_image_url = ""
    var app_name = "Silent VPN"
    var support_url = "https://t.me/silentvpn3?direct"
    var telegram_channel_url = "https://t.me/silentvpn3"
    var telegram_proxy_url = ""
    var telegram_proxy_menu_label = "Ускорить Telegram"
    var privacy_url = ""
    var terms_url = ""
    var update_bar_background_color = "#2563EB"
    var update_bar_text_color = "#FFFFFF"
    var login_link_color = "#4680C2"
    var login_remember_me_label = "Запомнить меня"
    var login_forgot_password_label = "Забыли пароль?"
    var login_forgot_title = "Восстановление пароля"
    var login_forgot_instruction = "Введите email — мы отправим ссылку для установки нового пароля."
    var menu_bonuses_label = "Бонусы"
    var bonuses_title = "Бонусы"
    var bonuses_intro_text = "Рефералка: отправьте другу ссылку или код. Он регистрируется по ним и оплачивает любую подписку — оба получаете +30 дней. Один бонус на одного друга, до 10 наград за 30 дней.\n\nПромокод: отдельная скидка или доп. дни к тарифу — вводится при регистрации или проверяется здесь.\n\nУсловия программы могут измениться."
    var bonuses_referral_title = "Ваша ссылка"
    var bonuses_referral_hint = "Скопируйте и отправьте другу"
    var bonuses_promo_title = "Промокод"
    var bonuses_promo_hint = "Проверить скидку к тарифу"
    var bonuses_copy_link_label = "Копировать ссылку"
    var bonuses_copy_code_label = "Копировать код"
    var register_referral_or_promo_label = "Промокод или реферальный код"
    var register_referral_or_promo_hint = "Необязательно. Введите промокод или код из реферальной ссылки."
    var payment_waiting_title = "Ждём подтверждения оплаты"
    var payment_waiting_text = "Оплатите в открывшейся вкладке браузера. После оплаты вернитесь в приложение — подписка активируется автоматически, обычно в течение минуты."
    var payment_success_title = "Оплата прошла успешно"
    var payment_success_text = "Подписка активирована. Спасибо за покупку!"
    var payment_failed_title = "Оплата не прошла"
    var payment_failed_text = "Платёж не был подтверждён. Попробуйте снова или обратитесь в поддержку."
    var payment_timeout_title = "Не дождались оплаты"
    var payment_timeout_text = "Если вы уже оплатили — подождите ещё немного или проверьте позже в разделе «Подписка»."
    var payment_retry_button_text = "Попробовать снова"
    var payment_cancel_button_text = "Отмена"
    var subscription_tier_3_label = "3 устройства"
    var subscription_tier_5_label = "5 устройств"
    var subscription_choose_tier_title = "Сколько устройств"
    var subscription_choose_plan_title = "Выберите тариф"
    var subscription_pay_early_label = "Оплатить заранее"
    var subscription_renewal_title = "Продление подписки"
    var subscription_renewal_confirm_label = "Перейти к оплате"
    var hive_standby_api_urls = ""
    var skip_email_confirmation: Bool?
    var dark_background_color = ""
    var dark_text_color = ""
    var dark_primary_color = ""
    var dark_toggle_on_color = ""
    var dark_toggle_off_color = ""
    var dark_login_link_color = ""

    init(dict: [String: Any] = [:]) {
        func s(_ key: String, _ def: String) -> String {
            let v = (dict[key] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return v.isEmpty ? def : v
        }
        func opt(_ key: String) -> String {
            (dict[key] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        }
        primary_color = s("primary_color", primary_color)
        background_color = s("background_color", background_color)
        text_color = s("text_color", text_color)
        accent_color = s("accent_color", accent_color)
        toggle_on_color = s("toggle_on_color", toggle_on_color)
        toggle_off_color = s("toggle_off_color", toggle_off_color)
        font_family = s("font_family", font_family)
        logo_url = opt("logo_url")
        home_bg_image_url = opt("home_bg_image_url")
        app_name = s("app_name", app_name)
        support_url = s("support_url", support_url)
        telegram_channel_url = s("telegram_channel_url", telegram_channel_url)
        telegram_proxy_url = opt("telegram_proxy_url")
        telegram_proxy_menu_label = s("telegram_proxy_menu_label", telegram_proxy_menu_label)
        privacy_url = opt("privacy_url")
        terms_url = opt("terms_url")
        update_bar_background_color = s("update_bar_background_color", update_bar_background_color)
        update_bar_text_color = s("update_bar_text_color", update_bar_text_color)
        login_link_color = s("login_link_color", login_link_color)
        login_remember_me_label = s("login_remember_me_label", login_remember_me_label)
        login_forgot_password_label = s("login_forgot_password_label", login_forgot_password_label)
        login_forgot_title = s("login_forgot_title", login_forgot_title)
        login_forgot_instruction = s("login_forgot_instruction", login_forgot_instruction)
        menu_bonuses_label = s("menu_bonuses_label", menu_bonuses_label)
        bonuses_title = s("bonuses_title", bonuses_title)
        bonuses_intro_text = s("bonuses_intro_text", bonuses_intro_text)
        bonuses_referral_title = s("bonuses_referral_title", bonuses_referral_title)
        bonuses_referral_hint = s("bonuses_referral_hint", bonuses_referral_hint)
        bonuses_promo_title = s("bonuses_promo_title", bonuses_promo_title)
        bonuses_promo_hint = s("bonuses_promo_hint", bonuses_promo_hint)
        bonuses_copy_link_label = s("bonuses_copy_link_label", bonuses_copy_link_label)
        bonuses_copy_code_label = s("bonuses_copy_code_label", bonuses_copy_code_label)
        register_referral_or_promo_label = s("register_referral_or_promo_label", register_referral_or_promo_label)
        register_referral_or_promo_hint = s("register_referral_or_promo_hint", register_referral_or_promo_hint)
        payment_waiting_title = s("payment_waiting_title", payment_waiting_title)
        payment_waiting_text = s("payment_waiting_text", payment_waiting_text)
        payment_success_title = s("payment_success_title", payment_success_title)
        payment_success_text = s("payment_success_text", payment_success_text)
        payment_failed_title = s("payment_failed_title", payment_failed_title)
        payment_failed_text = s("payment_failed_text", payment_failed_text)
        payment_timeout_title = s("payment_timeout_title", payment_timeout_title)
        payment_timeout_text = s("payment_timeout_text", payment_timeout_text)
        payment_retry_button_text = s("payment_retry_button_text", payment_retry_button_text)
        payment_cancel_button_text = s("payment_cancel_button_text", payment_cancel_button_text)
        subscription_tier_3_label = s("subscription_tier_3_label", subscription_tier_3_label)
        subscription_tier_5_label = s("subscription_tier_5_label", subscription_tier_5_label)
        subscription_choose_tier_title = s("subscription_choose_tier_title", subscription_choose_tier_title)
        subscription_choose_plan_title = s("subscription_choose_plan_title", subscription_choose_plan_title)
        subscription_pay_early_label = s("subscription_pay_early_label", subscription_pay_early_label)
        subscription_renewal_title = s("subscription_renewal_title", subscription_renewal_title)
        subscription_renewal_confirm_label = s("subscription_renewal_confirm_label", subscription_renewal_confirm_label)
        hive_standby_api_urls = opt("hive_standby_api_urls")
        if let flag = dict["skip_email_confirmation"] as? Bool {
            skip_email_confirmation = flag
        } else if let raw = dict["skip_email_confirmation"] as? String {
            skip_email_confirmation = raw.lowercased() == "true"
        }
        dark_background_color = opt("dark_background_color")
        dark_text_color = opt("dark_text_color")
        dark_primary_color = opt("dark_primary_color")
        dark_toggle_on_color = opt("dark_toggle_on_color")
        dark_toggle_off_color = opt("dark_toggle_off_color")
        dark_login_link_color = opt("dark_login_link_color")
    }
}

enum ServerCatalog {
    static let slots: [(key: String, title: String)] = [
        ("server1", "Сервер 1"),
        ("server2", "Сервер 2"),
        ("server3", "Сервер 3"),
        ("server4", "Сервер 4 для ИИ"),
        ("server5", "Сервер 5"),
    ]

    static func bakedIP(_ key: String) -> String? {
        switch key {
        case "server1": return "89.125.188.100"
        case "server2": return "87.58.213.193"
        case "server3": return "78.17.74.27"
        case "server4": return "192.177.26.38"
        case "server5": return "89.37.192.241"
        default: return nil
        }
    }

    static func mtu(slot: String, ip: String) -> Int {
        if slot == "server3" || ip == "78.17.74.27" { return 1420 }
        return 1200
    }
}
